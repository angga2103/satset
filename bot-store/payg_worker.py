import time
import datetime
import logging
import threading
import database
import pakasir
import xray_manager
from config import load_config

logger = logging.getLogger("payg_worker")

def process_pending_transactions(bot=None):
    """Check pending Pakasir transactions and credit users"""
    pending = database.get_pending_transactions()
    if not pending:
        return

    for tx in pending:
        order_id = tx["order_id"]
        user_id = tx["user_id"]
        res = pakasir.check_transaction(order_id)
        
        status = res.get("status")
        if status == "completed":
            completed = database.complete_transaction(order_id)
            if completed:
                logger.info(f"Payment completed for order {order_id}, credited user {user_id}")
                if bot:
                    try:
                        amount = completed["amount"]
                        new_bal = database.get_balance(user_id)
                        text = (
                            f"🎉 <b>PEMBAYARAN BERHASIL!</b>\n\n"
                            f"Order ID: <code>{order_id}</code>\n"
                            f"Nominal: <b>Rp {amount:,}</b>\n"
                            f"Saldo Sekarang: <b>Rp {new_bal:,}</b>\n\n"
                            f"Terima kasih telah melakukan top up! Silakan gunakan saldo Anda untuk membeli akun VPN atau mengaktifkan paket PAYG."
                        )
                        bot.send_message(user_id, text, parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Failed to notify user {user_id} of payment: {e}")

        elif status == "expired":
            conn = database.get_connection()
            c = conn.cursor()
            c.execute("UPDATE transactions SET status = 'expired' WHERE order_id = ?", (order_id,))
            conn.commit()
            conn.close()

def process_payg_daily(bot=None):
    """Perform daily deductions for PAYG accounts"""
    cfg = load_config()
    daily_price = cfg.get("PRICE_PAYG_DAILY", 300)
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    active_subs = database.get_active_payg_daily_subscriptions()
    for sub in active_subs:
        sub_id = sub["id"]
        user_id = sub["user_id"]
        username = sub["vpn_username"]
        proto = sub["protocol"]
        last_deducted = sub["last_deducted_date"]

        # If already deducted today, skip
        if last_deducted == today:
            continue

        # Try to deduct daily fee
        success = database.deduct_balance(user_id, daily_price)
        if success:
            database.update_payg_deduction(sub_id, today)
            new_bal = database.get_balance(user_id)
            logger.info(f"PAYG daily deducted Rp {daily_price} from user {user_id} for {username}")
            if bot:
                try:
                    text = (
                        f"⚡ <b>PAYG AUTO-DEBET BERHASIL</b>\n\n"
                        f"Akun: <code>{username}</code> ({proto.upper()})\n"
                        f"Tarif Harian: <b>Rp {daily_price:,}</b>\n"
                        f"Sisa Saldo: <b>Rp {new_bal:,}</b>\n\n"
                        f"Layanan Anda aktif sampai besok."
                    )
                    bot.send_message(user_id, text, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to send PAYG alert to {user_id}: {e}")
        else:
            # Insufficient funds -> suspend account
            database.set_payg_status(sub_id, "suspended")
            xray_manager.delete_account(proto, username)
            logger.warning(f"User {user_id} insufficient funds for PAYG {username}, suspended.")
            if bot:
                try:
                    text = (
                        f"⚠️ <b>PAYG DINONAKTIFKAN (SALDO TIDAK CUKUP)</b>\n\n"
                        f"Akun: <code>{username}</code> ({proto.upper()})\n"
                        f"Tarif Harian: <b>Rp {daily_price:,}</b>\n"
                        f"Saldo Anda tidak mencukupi untuk perpanjangan harian.\n\n"
                        f"Silakan /topup saldo Anda dan aktifkan kembali akun Anda."
                    )
                    bot.send_message(user_id, text, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to send PAYG suspend alert to {user_id}: {e}")

def run_worker_loop(bot=None):
    """Main worker loop running in background thread"""
    logger.info("Background PAYG and Pakasir worker started.")
    last_daily_check = 0

    while True:
        try:
            # 1. Check pending transactions every 10 seconds
            process_pending_transactions(bot)

            # 2. Check PAYG daily deductions every 5 minutes
            now_ts = time.time()
            if now_ts - last_daily_check > 300:
                process_payg_daily(bot)
                last_daily_check = now_ts

        except Exception as e:
            logger.error(f"Worker loop error: {e}")

        time.sleep(10)

def start_background_worker(bot=None):
    """Start worker in a daemon thread"""
    t = threading.Thread(target=run_worker_loop, args=(bot,), daemon=True)
    t.start()
    return t

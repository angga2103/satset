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

def process_limiter_and_violations(bot=None):
    """Enforce dynamic rules:
    1. Check and automatically unsuspend accounts whose suspension duration has expired.
    2. Check active sessions for multi-login IP violations and apply auto-suspension (e.g. 10 mins).
    3. Check quota limits for quota exceeded violations.
    """
    cfg = load_config()
    admin_id = cfg.get("ADMIN_ID")
    auto_suspend = bool(cfg.get("AUTO_SUSPEND_ENABLED", 1))
    suspend_duration = int(cfg.get("SUSPEND_DURATION_MINUTES", 10))

    # --- 1. Check expired suspensions (Auto-Unsuspend) ---
    locked_accounts = database.get_locked_accounts()
    now = datetime.datetime.now()

    for acc in locked_accounts:
        uname = acc["vpn_username"]
        proto = acc["protocol"]
        user_id = acc["user_id"]
        locked_until_str = acc.get("locked_until")
        reason = acc.get("lock_reason", "")

        # Only auto-unsuspend temporary locks, not quota_exceeded
        if reason == "quota_exceeded":
            continue

        if locked_until_str:
            try:
                locked_until = datetime.datetime.strptime(locked_until_str, "%Y-%m-%d %H:%M:%S")
                if now >= locked_until:
                    logger.info(f"Lock expired for user {uname}. Restoring account...")
                    xray_manager.unsuspend_account(proto, uname)
                    if bot:
                        try:
                            text_user = (
                                f"❇️ <b>AKUN DIAKTIFKAN KEMBALI</b>\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"» Akun: <code>{uname}</code> ({proto.upper()})\n"
                                f"» Status: <b>Aktif Normal</b>\n"
                                f"» Masa suspen pelanggaran telah selesai. Mohon untuk mematuhi aturan batasan IP!"
                            )
                            bot.send_message(user_id, text_user, parse_mode="HTML")
                        except Exception as e:
                            logger.error(f"Failed to notify user {user_id} of unsuspend: {e}")

                        if admin_id:
                            try:
                                text_admin = f"ℹ️ <b>[Auto-Unban]</b> Akun <code>{uname}</code> ({proto}) telah otomatis dipulihkan setelah masa suspen selesai."
                                bot.send_message(admin_id, text_admin, parse_mode="HTML")
                            except Exception:
                                pass
            except Exception as e:
                logger.error(f"Error parsing locked_until for {uname}: {e}")

    # --- 2. Check active IP multi-login violations ---
    if auto_suspend:
        active_sessions = xray_manager.get_active_sessions()
        for uname, ips in active_sessions.items():
            acc = database.get_account_by_username(uname)
            if not acc:
                continue

            if acc.get("status") == "suspended":
                continue

            proto = acc.get("protocol", "vmess")
            user_id = acc.get("user_id")
            ip_limit = acc.get("ip_limit") or cfg.get("DEFAULT_IP_LIMIT", 1)

            if len(ips) > ip_limit:
                logger.warning(f"Violation: user {uname} exceeded IP limit ({len(ips)} > {ip_limit}). Suspending for {suspend_duration}m...")
                until_str = xray_manager.suspend_account(proto, uname, duration_minutes=suspend_duration, reason="multi_login")
                
                if bot:
                    try:
                        ips_sample = ", ".join(ips[:3])
                        if len(ips) > 3:
                            ips_sample += f" (+{len(ips)-3} lainnya)"

                        text_violator = (
                            f"⚠️ <b>PERINGATAN: AKUN DITANGGUHKAN SEMENTARA</b>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"» Akun: <code>{uname}</code> ({proto.upper()})\n"
                            f"» Pelanggaran: <b>Multi-Login Melebihi Batas</b>\n"
                            f"» Batas IP: <code>{ip_limit} IP</code>\n"
                            f"» IP Terdeteksi: <code>{len(ips)} IP</code> ({ips_sample})\n"
                            f"» Sanksi: <b>Akun Dimatikan {suspend_duration} Menit</b>\n"
                            f"» Aktif Kembali: <code>{until_str}</code>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🤖 <i>Akun Anda akan otomatis aktif kembali setelah {suspend_duration} menit. Mohon tidak berbagi akun!</i>"
                        )
                        bot.send_message(user_id, text_violator, parse_mode="HTML")
                    except Exception as e:
                        logger.error(f"Failed to alert user {user_id} of suspension: {e}")

                    if admin_id:
                        try:
                            text_adm = (
                                f"🚨 <b>NOTIFIKASI PELANGGARAN MULTI-LOGIN</b>\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"» User: <code>{uname}</code> ({proto})\n"
                                f"» Terdeteksi: <b>{len(ips)} IP Aktif</b> (Batas: {ip_limit} IP)\n"
                                f"» IP: <code>{', '.join(ips)}</code>\n"
                                f"» Tindakan: <b>Disuspen {suspend_duration} Menit</b>\n"
                                f"» Berakhir: <code>{until_str}</code>"
                            )
                            bot.send_message(admin_id, text_adm, parse_mode="HTML")
                        except Exception:
                            pass

    # --- 3. Check quota limits ---
    all_accounts = database.get_all_vpn_accounts_detailed(limit=200)
    for acc in all_accounts:
        if acc.get("status") == "suspended":
            continue

        uname = acc["vpn_username"]
        proto = acc["protocol"]
        user_id = acc["user_id"]
        
        status_info = xray_manager.get_user_usage_and_status(uname, proto)
        quota_bytes = status_info.get("quota_bytes", 0)
        used_bytes = status_info.get("used_bytes", 0)

        if quota_bytes > 0 and used_bytes >= quota_bytes:
            logger.warning(f"Quota exceeded for user {uname} ({status_info['used_human']} >= {status_info['quota_human']}). Suspending...")
            xray_manager.suspend_account(proto, uname, duration_minutes=525600, reason="quota_exceeded")

            if bot:
                try:
                    text_quota = (
                        f"⚠️ <b>KUOTA PEMAKAIAN TELAH HABIS</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"» Akun: <code>{uname}</code> ({proto.upper()})\n"
                        f"» Pemakaian: <b>{status_info['used_human']} / {status_info['quota_human']}</b>\n"
                        f"» Status: <b>Akun Dinonaktifkan</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"Silakan hubungi Admin atau perpanjang paket untuk menambah kuota."
                    )
                    bot.send_message(user_id, text_quota, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id} of quota expiry: {e}")

def run_worker_loop(bot=None):
    """Main worker loop running in background thread"""
    logger.info("Background PAYG, Pakasir, and Limiter worker started.")
    last_daily_check = 0
    last_limiter_check = 0

    while True:
        try:
            # 1. Check pending transactions every 10 seconds
            process_pending_transactions(bot)

            # 2. Check limiter & multi-login violations every 30 seconds
            now_ts = time.time()
            if now_ts - last_limiter_check >= 30:
                process_limiter_and_violations(bot)
                last_limiter_check = now_ts

            # 3. Check PAYG daily deductions every 5 minutes
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


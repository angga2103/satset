import os
import sys
import io
import re
import time
import uuid
import datetime
import logging
import telebot
from telebot import types

import qrcode
from config import load_config, save_config, update_config_key, get_rules_summary, is_admin
import database
import pakasir
import xray_manager
import payg_worker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("satset_bot")

cfg = load_config()
BOT_TOKEN = cfg.get("BOT_TOKEN")
ADMIN_ID = cfg.get("ADMIN_ID")

if not BOT_TOKEN:
    logger.warning("BOT_TOKEN is empty! Please set BOT_TOKEN in /etc/satset/bot.env or via bot.py environment.")

bot = telebot.TeleBot(BOT_TOKEN or "DUMMY_TOKEN", parse_mode="HTML")

# User state storage for multi-step prompts (e.g. entering username, custom amount, broadcast)
user_states = {}

# Helper keyboards
def main_menu_keyboard(user_id: int):
    markup = types.InlineKeyboardMarkup(row_width=2)
    b1 = types.InlineKeyboardButton("🛒 Beli Akun (30 Hari)", callback_data="menu_buy_monthly")
    b2 = types.InlineKeyboardButton("⚡ Akun PAYG (Harian)", callback_data="menu_buy_payg")
    b3 = types.InlineKeyboardButton("🎁 Trial Gratis (1 Hari)", callback_data="menu_trial")
    b4 = types.InlineKeyboardButton("💳 Isi Saldo (QRIS)", callback_data="menu_topup")
    b5 = types.InlineKeyboardButton("📱 Akun Saya", callback_data="menu_my_accounts")
    b6 = types.InlineKeyboardButton("📊 Info Server", callback_data="menu_server_info")
    markup.add(b1, b2)
    markup.add(b3, b4)
    markup.add(b5, b6)
    
    # Check if admin
    if is_admin(user_id):
        b_admin = types.InlineKeyboardButton("🛠️ Admin Panel", callback_data="menu_admin")
        markup.add(b_admin)
        
    return markup

def back_home_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home"))
    return markup

def render_admin_panel(user_id: int):
    stats = database.get_total_stats()
    active_sessions = xray_manager.get_active_sessions()
    locked_accs = database.get_locked_accounts()

    text = (
        f"🛠️ <b>ADMINISTRATOR PANEL</b>\n\n"
        f"👥 Total Pengguna Bot : <b>{stats['users']}</b>\n"
        f"📱 Total Akun VPN     : <b>{stats['accounts']}</b>\n"
        f"🟢 User Sedang Online  : <b>{len(active_sessions)} User</b>\n"
        f"🔒 Akun Terkunci      : <b>{len(locked_accs)} Akun</b>\n"
        f"💰 Total Omset QRIS   : <b>Rp {stats['revenue']:,}</b>\n\n"
        f"Pilih menu manajemen di bawah ini:"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    b_rules = types.InlineKeyboardButton("⚙️ Rules & Tarif Server", callback_data="admin_rules_menu")
    b_mon = types.InlineKeyboardButton("👥 Live Monitoring & User", callback_data="admin_monitor_users")
    b_lock = types.InlineKeyboardButton(f"🔒 Akun Terkunci ({len(locked_accs)})", callback_data="admin_list_suspended")
    b_saldo = types.InlineKeyboardButton("➕ Tambah Saldo User", callback_data="admin_addsaldo_prompt")
    b_bc = types.InlineKeyboardButton("📢 Broadcast Pesan", callback_data="admin_broadcast")
    b_users = types.InlineKeyboardButton("📋 List Pengguna Bot", callback_data="admin_list_users")
    b_back = types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home")
    
    markup.add(b_rules, b_mon)
    markup.add(b_lock, b_saldo)
    markup.add(b_bc, b_users)
    markup.add(b_back)
    return text, markup

# --- Handlers ---

@bot.message_handler(commands=['admin'])
def cmd_admin(message):
    user_id = message.from_user.id
    if is_admin(user_id):
        text, markup = render_admin_panel(user_id)
        bot.send_message(user_id, text, reply_markup=markup)
    else:
        bot.reply_to(
            message,
            f"🚫 <b>Akses Ditolak</b>\n\n"
            f"Akun Telegram Anda saat ini terdaftar sebagai <b>Member</b>, bukan Admin.\n\n"
            f"🆔 <b>ID Telegram Anda:</b> <code>{user_id}</code>\n\n"
            f"💡 <b>Cara Mengaktifkan Akses Admin:</b>\n"
            f"1. Buka file env di VPS:\n"
            f"   <code>nano /etc/satset/bot.env</code>\n"
            f"2. Pastikan baris ADMIN_ID diisi:\n"
            f"   <code>ADMIN_ID={user_id}</code>\n"
            f"3. Simpan dan restart bot:\n"
            f"   <code>systemctl restart satset-bot</code>\n"
            f"4. Ketik lagi <code>/admin</code> atau <code>/start</code>"
        )

@bot.message_handler(commands=['start', 'menu'])
def cmd_start(message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or ""
    
    cfg = load_config()
    admin_id = cfg.get("ADMIN_ID")
    u = database.get_or_create_user(user_id, username, first_name, admin_id)
    
    domain = xray_manager.get_domain()
    bal = u.get("balance", 0)
    role_str = "👑 <b>ADMINISTRATOR</b>" if is_admin(user_id) else "👤 <b>Member</b>"
    
    text = (
        f"👋 <b>Halo, {first_name}!</b>\n\n"
        f"Selamat datang di <b>SATSET Tunneling Store</b>.\n"
        f"Layanan VPN Premium berkecepatan tinggi dengan berbagai protokol modern.\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Info Pengguna:</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"🔰 Status: {role_str}\n"
        f"💰 Saldo: <b>Rp {bal:,}</b>\n"
        f"🌐 Host/Domain: <code>{domain}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Silakan pilih menu di bawah ini:"
    )
    bot.send_message(user_id, text, reply_markup=main_menu_keyboard(user_id))

# Topup menu
@bot.callback_query_handler(func=lambda call: call.data == "menu_topup")
def callback_topup(call):
    user_id = call.from_user.id
    bal = database.get_balance(user_id)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    b1 = types.InlineKeyboardButton("Rp 5.000", callback_data="topup_amt_5000")
    b2 = types.InlineKeyboardButton("Rp 8.000 (1 Bulan)", callback_data="topup_amt_8000")
    b3 = types.InlineKeyboardButton("Rp 10.000", callback_data="topup_amt_10000")
    b4 = types.InlineKeyboardButton("Rp 20.000", callback_data="topup_amt_20000")
    b5 = types.InlineKeyboardButton("Rp 50.000", callback_data="topup_amt_5000")
    b6 = types.InlineKeyboardButton("✏️ Nominal Custom", callback_data="topup_amt_custom")
    b_back = types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home")
    
    markup.add(b1, b2)
    markup.add(b3, b4)
    markup.add(b5, b6)
    markup.add(b_back)
    
    text = (
        f"💳 <b>ISI SALDO OTOMATIS (QRIS)</b>\n\n"
        f"Saldo Anda Saat Ini: <b>Rp {bal:,}</b>\n\n"
        f"Pembayaran instan didukung oleh <b>Pakasir QRIS Real-Time</b>.\n"
        f"Bisa dibayar dengan GoPay, OVO, DANA, ShopeePay, BCA, Mandiri, BRI, BNI & seluruh bank/e-wallet berlogo QRIS.\n\n"
        f"Pilih nominal top up yang Anda inginkan:"
    )
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("topup_amt_"))
def callback_topup_amount(call):
    user_id = call.from_user.id
    amt_str = call.data.replace("topup_amt_", "")
    
    if amt_str == "custom":
        user_states[user_id] = {"action": "wait_custom_topup"}
        text = "✏️ Masukkan nominal isi saldo yang Anda inginkan (Contoh: <code>15000</code>, minimal Rp 1.000):"
        bot.send_message(user_id, text, reply_markup=back_home_keyboard())
        return

    try:
        amount = int(amt_str)
        initiate_qris_payment(user_id, amount)
    except Exception as e:
        bot.send_message(user_id, f"Gagal membuat transaksi: {e}")

def initiate_qris_payment(user_id: int, amount: int):
    if amount < 1000:
        bot.send_message(user_id, "Nominal minimal isi saldo adalah Rp 1.000.")
        return

    order_id = f"SATSET-{user_id}-{int(time.time())}"
    wait_msg = bot.send_message(user_id, "⏳ <i>Sedang membuat barcode QRIS Pakasir...</i>")
    
    res = pakasir.create_qris(order_id, amount)
    try:
        bot.delete_message(user_id, wait_msg.message_id)
    except Exception:
        pass

    if not res.get("success"):
        bot.send_message(user_id, f"❌ <b>Gagal membuat pembayaran QRIS:</b>\n{res.get('error')}", reply_markup=back_home_keyboard())
        return

    qr_url = res.get("qr_url", "")
    qr_string = res.get("qr_string", "")
    total_payment = res.get("total_payment") or amount
    fee = res.get("fee", 0)
    database.create_transaction(order_id, user_id, amount, qr_url, qr_string)

    markup = types.InlineKeyboardMarkup(row_width=1)
    b_check = types.InlineKeyboardButton("🔄 Cek Status Pembayaran", callback_data=f"check_tx_{order_id}")
    b_cancel = types.InlineKeyboardButton("❌ Batalkan", callback_data="menu_home")
    markup.add(b_check, b_cancel)

    fee_text = f"\nBiaya Admin/Kode Unik: <b>Rp {fee:,}</b>" if fee > 0 else ""
    caption = (
        f"🧾 <b>INVOICE PEMBAYARAN QRIS</b>\n\n"
        f"Order ID: <code>{order_id}</code>\n"
        f"Nominal Saldo: <b>Rp {amount:,}</b>"
        f"{fee_text}\n"
        f"Total Bayar: <b>Rp {total_payment:,}</b>\n"
        f"Metode: <b>QRIS Real-Time</b>\n\n"
        f"⚠️ <i>Harap transfer tepat sesuai <b>Total Bayar</b> agar saldo otomatis masuk!</i>\n\n"
        f"📌 <b>Cara Pembayaran:</b>\n"
        f"1. Simpan/Screenshot gambar QR Code di atas\n"
        f"2. Buka aplikasi M-Banking atau E-Wallet (Dana, OVO, Gopay, BCA, ShopeePay, dll)\n"
        f"3. Pilih menu <b>Scan QRIS</b> dan upload gambar barcode\n"
        f"4. Selesaikan pembayaran\n"
        f"5. Klik tombol <b>Cek Status Pembayaran</b> di bawah atau tunggu beberapa detik!"
    )

    # If qr_string is available, generate QR Code image using qrcode lib
    if qr_string:
        try:
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data(qr_string)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            
            bot.send_photo(user_id, photo=buf, caption=caption, reply_markup=markup)
            return
        except Exception as e:
            logger.error(f"Failed to generate QR image: {e}")

    # Fallback to URL or text
    if qr_url:
        caption += f"\n\n🔗 <a href='{qr_url}'>Klik di sini untuk melihat barcode QRIS</a>"
    bot.send_message(user_id, caption, reply_markup=markup, disable_web_page_preview=False)

@bot.callback_query_handler(func=lambda call: call.data.startswith("check_tx_"))
def callback_check_tx(call):
    user_id = call.from_user.id
    order_id = call.data.replace("check_tx_", "")
    
    res = pakasir.check_transaction(order_id)
    status = res.get("status")

    if status == "completed":
        completed = database.complete_transaction(order_id)
        bal = database.get_balance(user_id)
        text = (
            f"🎉 <b>PEMBAYARAN BERHASIL!</b>\n\n"
            f"Order ID: <code>{order_id}</code>\n"
            f"Saldo Anda Sekarang: <b>Rp {bal:,}</b>\n\n"
            f"Terima kasih atas pembayaran Anda!"
        )
        bot.send_message(user_id, text, reply_markup=main_menu_keyboard(user_id))
    elif status == "pending":
        bot.answer_callback_query(call.id, "Pembayaran belum terdeteksi. Silakan bayar terlebih dahulu lalu cek lagi.", show_alert=True)
    elif status == "expired":
        bot.send_message(user_id, "⚠️ Invoice ini telah kadaluarsa. Silakan buat transaksi baru.", reply_markup=back_home_keyboard())
    else:
        bot.answer_callback_query(call.id, f"Status: {status}", show_alert=True)

# Monthly package flow
@bot.callback_query_handler(func=lambda call: call.data == "menu_buy_monthly")
def callback_buy_monthly(call):
    user_id = call.from_user.id
    cfg = load_config()
    price = cfg.get("PRICE_MONTHLY", 8000)
    bal = database.get_balance(user_id)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    b0 = types.InlineKeyboardButton("🔑 SSH & WebSocket", callback_data="buy_monthly_ssh")
    b1 = types.InlineKeyboardButton("🚀 VMess (WS / gRPC)", callback_data="buy_monthly_vmess")
    b2 = types.InlineKeyboardButton("⚡ VLess (WS / gRPC)", callback_data="buy_monthly_vless")
    b3 = types.InlineKeyboardButton("🛡️ Trojan (WS / gRPC)", callback_data="buy_monthly_trojan")
    b4 = types.InlineKeyboardButton("🔒 Shadowsocks", callback_data="buy_monthly_shadowsocks")
    b_back = types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home")
    markup.add(b0)
    markup.add(b1, b2)
    markup.add(b3, b4)
    markup.add(b_back)
    
    text = (
        f"🛒 <b>BELI PAKET BULANAN (30 HARI)</b>\n\n"
        f"Harga: <b>Rp {price:,} / 30 Hari</b>\n"
        f"Saldo Anda: <b>Rp {bal:,}</b>\n\n"
        f"✨ <i>Fitur:</i> Kuota Unlimited, High Speed, Port TLS & Non-TLS, Support SSH, Xray & Clash.\n\n"
        f"Silakan pilih protokol yang diinginkan:"
    )
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_monthly_"))
def callback_choose_monthly_proto(call):
    user_id = call.from_user.id
    proto = call.data.replace("buy_monthly_", "")
    cfg = load_config()
    price = cfg.get("PRICE_MONTHLY", 8000)
    bal = database.get_balance(user_id)
    
    if bal < price:
        markup = types.InlineKeyboardMarkup()
        b_topup = types.InlineKeyboardButton("💳 Isi Saldo Sekarang", callback_data="menu_topup")
        b_back = types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home")
        markup.add(b_topup)
        markup.add(b_back)
        
        text = (
            f"❌ <b>Saldo Tidak Mencukupi!</b>\n\n"
            f"Harga Paket: <b>Rp {price:,}</b>\n"
            f"Saldo Anda: <b>Rp {bal:,}</b>\n\n"
            f"Silakan isi saldo Anda terlebih dahulu untuk melanjutkan pembelian."
        )
        bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)
        return

    user_states[user_id] = {
        "action": "wait_username_monthly",
        "proto": proto,
        "price": price
    }
    
    text = (
        f"📝 <b>MEMBUAT AKUN {proto.upper()} (30 HARI)</b>\n\n"
        f"Silakan ketik <b>Username</b> yang Anda inginkan:\n"
        f"<i>(Hanya huruf dan angka, tanpa spasi, 3-15 karakter)</i>"
    )
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

# PAYG flow
@bot.callback_query_handler(func=lambda call: call.data == "menu_buy_payg")
def callback_buy_payg(call):
    user_id = call.from_user.id
    cfg = load_config()
    daily_price = cfg.get("PRICE_PAYG_DAILY", 300)
    bal = database.get_balance(user_id)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    b0 = types.InlineKeyboardButton("🔑 SSH PAYG", callback_data="buy_payg_ssh")
    b1 = types.InlineKeyboardButton("🚀 VMess PAYG", callback_data="buy_payg_vmess")
    b2 = types.InlineKeyboardButton("⚡ VLess PAYG", callback_data="buy_payg_vless")
    b3 = types.InlineKeyboardButton("🛡️ Trojan PAYG", callback_data="buy_payg_trojan")
    b4 = types.InlineKeyboardButton("🔒 Shadowsocks PAYG", callback_data="buy_payg_shadowsocks")
    b_back = types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home")
    markup.add(b0)
    markup.add(b1, b2)
    markup.add(b3, b4)
    markup.add(b_back)
    
    text = (
        f"⚡ <b>PAKET PAY-AS-YOU-GO (PAYG)</b>\n\n"
        f"Bayar sesuai pemakaian tanpa komitmen sebulan penuh!\n"
        f"Tarif Harian: <b>Rp {daily_price:,} / Hari</b>\n"
        f"Saldo Anda: <b>Rp {bal:,}</b>\n\n"
        f"💡 <i>Cara Kerja:</i>\n"
        f"• Akun aktif terus selama saldo Anda mencukupi.\n"
        f"• Setiap tengah malam (00:00 WIB), sistem otomatis memotong Rp {daily_price:,}.\n"
        f"• Sangat hemat jika hanya butuh beberapa hari atau fleksibel.\n\n"
        f"Pilih protokol yang diinginkan:"
    )
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_payg_"))
def callback_choose_payg_proto(call):
    user_id = call.from_user.id
    proto = call.data.replace("buy_payg_", "")
    cfg = load_config()
    daily_price = cfg.get("PRICE_PAYG_DAILY", 300)
    bal = database.get_balance(user_id)
    
    if bal < daily_price:
        markup = types.InlineKeyboardMarkup()
        b_topup = types.InlineKeyboardButton("💳 Isi Saldo", callback_data="menu_topup")
        b_back = types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home")
        markup.add(b_topup, b_back)
        
        text = (
            f"❌ <b>Saldo Kurang!</b>\n"
            f"Minimal saldo untuk mengaktifkan PAYG adalah <b>Rp {daily_price:,}</b>.\n"
            f"Saldo Anda: <b>Rp {bal:,}</b>."
        )
        bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)
        return

    user_states[user_id] = {
        "action": "wait_username_payg",
        "proto": proto,
        "daily_price": daily_price
    }
    
    text = (
        f"⚡ <b>AKTIVASI PAYG {proto.upper()}</b>\n\n"
        f"Biaya hari pertama sebesar Rp {daily_price:,} akan dipotong saat akun dibuat.\n"
        f"Silakan ketik <b>Username</b> yang Anda inginkan (3-15 karakter):"
    )
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

# Free Trial Flow
@bot.callback_query_handler(func=lambda call: call.data == "menu_trial")
def callback_trial(call):
    user_id = call.from_user.id
    if database.has_used_trial(user_id):
        bot.answer_callback_query(call.id, "Anda sudah pernah menggunakan fasilitas Trial Gratis 1 hari.", show_alert=True)
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    b0 = types.InlineKeyboardButton("🔑 SSH Trial", callback_data="take_trial_ssh")
    b1 = types.InlineKeyboardButton("🚀 VMess Trial", callback_data="take_trial_vmess")
    b2 = types.InlineKeyboardButton("⚡ VLess Trial", callback_data="take_trial_vless")
    b3 = types.InlineKeyboardButton("🛡️ Trojan Trial", callback_data="take_trial_trojan")
    b4 = types.InlineKeyboardButton("🔒 Shadowsocks Trial", callback_data="take_trial_shadowsocks")
    b_back = types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home")
    markup.add(b0)
    markup.add(b1, b2)
    markup.add(b3, b4)
    markup.add(b_back)

    text = (
        f"🎁 <b>TRIAL GRATIS (1 HARI)</b>\n\n"
        f"Nikmati akses gratis tanpa biaya selama 24 jam untuk mencoba kestabilan dan kecepatan server kami!\n\n"
        f"Pilih protokol untuk trial:"
    )
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("take_trial_"))
def callback_take_trial(call):
    user_id = call.from_user.id
    if database.has_used_trial(user_id):
        bot.answer_callback_query(call.id, "Anda sudah pernah menggunakan jatah Trial Gratis.", show_alert=True)
        return

    proto = call.data.replace("take_trial_", "")
    uname = f"trial{str(user_id)[-4:]}{int(time.time()) % 1000}"
    cfg = load_config()
    trial_quota = min(10, cfg.get("DEFAULT_QUOTA_GB", 350))
    trial_ip = cfg.get("DEFAULT_IP_LIMIT", 1)
    
    wait_msg = bot.send_message(user_id, f"⏳ <i>Membuat akun Trial {proto.upper()}...</i>")
    try:
        acc = xray_manager.create_account(proto, uname, days=1, quota_gb=trial_quota, ip_limit=trial_ip)
        database.add_vpn_account(user_id, proto, uname, acc["uuid"], "trial", acc["exp_date"], acc["primary_link"], quota_gb=trial_quota, ip_limit=trial_ip, price_paid=0)
        bot.delete_message(user_id, wait_msg.message_id)
        send_account_details(user_id, acc, title="🎉 AKUN TRIAL 1 HARI BERHASIL DIBUAT")
    except Exception as e:
        bot.send_message(user_id, f"Gagal membuat akun trial: {e}")

# My accounts list
@bot.callback_query_handler(func=lambda call: call.data == "menu_my_accounts")
def callback_my_accounts(call):
    user_id = call.from_user.id
    accounts = database.get_user_vpn_accounts(user_id)

    if not accounts:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🛒 Beli Akun Sekarang", callback_data="menu_buy_monthly"))
        markup.add(types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home"))
        text = "📱 <b>Anda belum memiliki akun VPN.</b>\nSilakan pilih paket untuk membeli akun."
        bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    for acc in accounts[:10]:
        status_icon = "🟢" if acc["status"] == "active" else "🔴"
        btn_text = f"{status_icon} {acc['protocol'].upper()} - {acc['vpn_username']} ({acc['plan_type'].upper()})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"detail_acc_{acc['id']}"))
        
    markup.add(types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home"))
    text = "📱 <b>DAFTAR AKUN VPN ANDA:</b>\nKlik salah satu akun untuk melihat detail & link config:"
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

def calculate_account_refund(acc: dict) -> dict:
    """Calculate refund amount and breakdown for account cancellation."""
    cfg = load_config()
    plan_type = str(acc.get("plan_type", "monthly")).lower()
    
    if plan_type == "payg":
        return {
            "plan_type": "payg",
            "price_paid": acc.get("price_paid") or cfg.get("PRICE_PAYG_DAILY", 300),
            "remaining_days": 0,
            "total_days": 1,
            "refund_amount": 0,
            "explanation": "Langganan auto-debet harian PAYG langsung dihentikan. Biaya harian yang sudah berjalan tidak ditarik ulang, dan saldo bot Anda tetap aman tanpa potongan lagi."
        }
    elif plan_type == "trial":
        return {
            "plan_type": "trial",
            "price_paid": 0,
            "remaining_days": 0,
            "total_days": 1,
            "refund_amount": 0,
            "explanation": "Akun trial gratis 1 hari dibatalkan dan dihapus dari server."
        }
    else:
        # Monthly or fixed duration package
        price_paid = acc.get("price_paid") or 0
        if price_paid <= 0:
            price_paid = cfg.get("PRICE_MONTHLY", 8000)
            
        exp_str = str(acc.get("exp_date", "")).strip()
        remaining_days = 0
        total_days = 30
        
        try:
            exp_date = datetime.datetime.strptime(exp_str[:10], "%Y-%m-%d").date()
            today = datetime.date.today()
            diff = (exp_date - today).days
            remaining_days = max(0, min(total_days, diff))
        except Exception:
            remaining_days = 0
            
        if remaining_days > 0 and price_paid > 0:
            refund_amount = int(round((remaining_days / float(total_days)) * price_paid))
        else:
            refund_amount = 0
            
        return {
            "plan_type": plan_type,
            "price_paid": price_paid,
            "remaining_days": remaining_days,
            "total_days": total_days,
            "refund_amount": refund_amount,
            "explanation": f"Refund pro-rata dihitung dari sisa masa aktif ({remaining_days}/{total_days} hari) x Rp {price_paid:,}."
        }

@bot.callback_query_handler(func=lambda call: call.data.startswith("detail_acc_"))
def callback_account_detail(call):
    user_id = call.from_user.id
    acc_id = int(call.data.replace("detail_acc_", ""))
    acc = database.get_vpn_account_by_id(acc_id)

    if not acc or acc["user_id"] != user_id:
        bot.answer_callback_query(call.id, "Akun tidak ditemukan.", show_alert=True)
        return

    domain = xray_manager.get_domain()
    proto = acc['protocol'].upper()
    uname = acc['vpn_username']
    pwd = acc['uuid']

    plan_type = str(acc.get('plan_type', 'monthly')).lower()
    raw_exp = str(acc.get('exp_date', ''))
    if plan_type == "payg" or raw_exp.upper() == "PAYG":
        exp_display = "⚡ Aktif Selama Saldo Cukup (PAYG Auto-Debet)"
        paket_display = "PAY-AS-YOU-GO (Harian)"
    elif plan_type == "trial":
        exp_display = f"{raw_exp} (Trial 1 Hari)"
        paket_display = "TRIAL (Uji Coba)"
    else:
        exp_display = raw_exp or "-"
        paket_display = f"{plan_type.upper()} (30 Hari)"

    quota_display = f"{acc.get('quota_gb', 0)} GB" if acc.get('quota_gb', 0) > 0 else "Unlimited"
    ip_display = f"{acc.get('ip_limit', 1)} IP"

    if acc['protocol'].lower() in ["ssh", "openssh", "dropbear"]:
        payload = f"GET / HTTP/1.1[crlf]Host: {domain}[crlf]Upgrade: websocket[crlf][crlf]"
        text = (
            f"📱 <b>DETAIL AKUN SSH & WEBSOCKET</b>\n\n"
            f"Username      : <code>{uname}</code>\n"
            f"Password      : <code>{pwd}</code>\n"
            f"Domain / Host : <code>{domain}</code>\n"
            f"Port OpenSSH  : <code>22</code>\n"
            f"Port Dropbear : <code>109, 143</code>\n"
            f"Port SSL/TLS  : <code>443, 777</code>\n"
            f"Port WS NonTLS: <code>80, 8080, 8880</code>\n"
            f"Port WS TLS   : <code>443, 8443</code>\n"
            f"BadVPN UDP GW : <code>7100, 7200, 7300</code>\n"
            f"Paket         : <b>{paket_display}</b>\n"
            f"Limit IP      : <code>{ip_display}</code>\n"
            f"Masa Aktif    : <b>{exp_display}</b>\n\n"
            f"🔗 <b>Payload WebSocket:</b>\n"
            f"<code>{payload}</code>"
        )
    else:
        text = (
            f"📱 <b>DETAIL AKUN VPN</b>\n\n"
            f"Protokol: <b>{proto}</b>\n"
            f"Username: <code>{uname}</code>\n"
            f"UUID / Password: <code>{pwd}</code>\n"
            f"Paket: <b>{paket_display}</b>\n"
            f"Limit IP: <code>{ip_display}</code>\n"
            f"Limit Kuota: <code>{quota_display}</code>\n"
            f"Masa Aktif: <b>{exp_display}</b>\n"
            f"Domain: <code>{domain}</code>\n\n"
            f"🔗 <b>Config Link:</b>\n"
            f"<code>{acc['config_link']}</code>"
        )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("❌ Batalkan & Hapus Akun (Refund Saldo)", callback_data=f"cancel_acc_{acc_id}"),
        types.InlineKeyboardButton("🔙 Kembali ke Daftar Akun", callback_data="menu_my_accounts")
    )
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cancel_acc_"))
def callback_cancel_account(call):
    user_id = call.from_user.id
    acc_id = int(call.data.replace("cancel_acc_", ""))
    acc = database.get_vpn_account_by_id(acc_id)

    if not acc or acc["user_id"] != user_id:
        bot.answer_callback_query(call.id, "Akun tidak ditemukan atau bukan milik Anda.", show_alert=True)
        return

    proto = acc["protocol"].upper()
    uname = acc["vpn_username"]
    plan_type = str(acc.get("plan_type", "monthly")).lower()
    ref_info = calculate_account_refund(acc)
    refund_amt = ref_info["refund_amount"]
    current_bal = database.get_balance(user_id)

    if plan_type == "payg":
        text = (
            f"⚠️ <b>KONFIRMASI PEMBATALAN AKUN PAYG</b>\n\n"
            f"Apakah Anda yakin ingin menghentikan & menghapus akun ini?\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Username:</b> <code>{uname}</code>\n"
            f"• <b>Protokol:</b> <code>{proto}</code>\n"
            f"• <b>Paket:</b> <b>PAY-AS-YOU-GO (Harian)</b>\n"
            f"• <b>Saldo Utama Saat Ini:</b> <b>Rp {current_bal:,}</b>\n"
            f"• <b>Refund Saldo:</b> <b>Rp 0</b> (Auto-Debet dihentikan)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>{ref_info['explanation']}</i>\n\n"
            f"Akun akan langsung dihapus dari server dan saldo utama Anda tidak akan terpotong lagi di kemudian hari."
        )
    elif plan_type == "trial":
        text = (
            f"⚠️ <b>KONFIRMASI HAPUS AKUN TRIAL</b>\n\n"
            f"Apakah Anda yakin ingin menghapus akun trial ini?\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Username:</b> <code>{uname}</code>\n"
            f"• <b>Protokol:</b> <code>{proto}</code>\n"
            f"• <b>Paket:</b> <b>TRIAL (Uji Coba 1 Hari)</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>{ref_info['explanation']}</i>\n\n"
            f"Akun akan langsung dihapus dari server."
        )
    else:
        text = (
            f"⚠️ <b>KONFIRMASI PEMBATALAN & REFUND AKUN</b>\n\n"
            f"Apakah Anda yakin ingin membatalkan langganan akun ini?\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Username:</b> <code>{uname}</code>\n"
            f"• <b>Protokol:</b> <code>{proto}</code>\n"
            f"• <b>Paket:</b> <b>BULANAN (30 Hari)</b>\n"
            f"• <b>Harga Beli:</b> <b>Rp {ref_info['price_paid']:,}</b>\n"
            f"• <b>Sisa Masa Aktif:</b> <b>{ref_info['remaining_days']} hari</b>\n"
            f"• <b>Estimasi Refund Saldo:</b> <b>Rp {refund_amt:,}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 <i>{ref_info['explanation']}</i>\n\n"
            f"Setelah dikonfirmasi:\n"
            f"1. Akun langsung dinonaktifkan & dihapus dari server.\n"
            f"2. Saldo refund sebesar <b>Rp {refund_amt:,}</b> akan otomatis dikreditkan kembali ke saldo bot Anda."
        )

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🗑️ Ya, Batalkan & Hapus Akun", callback_data=f"confirm_cancel_acc_{acc_id}"),
        types.InlineKeyboardButton("🔙 Jangan, Kembali ke Detail", callback_data=f"detail_acc_{acc_id}")
    )
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_cancel_acc_"))
def callback_confirm_cancel_account(call):
    user_id = call.from_user.id
    acc_id = int(call.data.replace("confirm_cancel_acc_", ""))
    acc = database.get_vpn_account_by_id(acc_id)

    if not acc or acc["user_id"] != user_id:
        bot.answer_callback_query(call.id, "Akun tidak ditemukan atau sudah dihapus.", show_alert=True)
        return

    proto = acc["protocol"].lower()
    uname = acc["vpn_username"]
    plan_type = str(acc.get("plan_type", "monthly")).lower()

    # Calculate refund
    ref_info = calculate_account_refund(acc)
    refund_amt = ref_info["refund_amount"]

    # 1. Delete from VPS server (xray / ssh)
    try:
        xray_manager.delete_account(proto, uname)
    except Exception as e:
        logger.error(f"Error deleting {uname} from server: {e}")

    # 2. Delete from database (removes from vpn_accounts & payg_subscriptions)
    database.delete_vpn_account_by_username(uname)

    # 3. Credit refund balance if > 0
    if refund_amt > 0:
        new_balance = database.add_balance(user_id, refund_amt)
        database.record_refund_transaction(user_id, refund_amt, f"Refund pembatalan akun {uname}")
    else:
        new_balance = database.get_balance(user_id)

    bot.answer_callback_query(call.id, "Akun berhasil dibatalkan dan dihapus.")

    success_text = (
        f"✅ <b>AKUN BERHASIL DIBATALKAN & DIHAPUS</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"• <b>Username:</b> <code>{uname}</code>\n"
        f"• <b>Protokol:</b> <code>{proto.upper()}</code>\n"
        f"• <b>Paket:</b> <b>{plan_type.upper()}</b>\n"
    )

    if refund_amt > 0:
        success_text += (
            f"• <b>Dana Refund:</b> <b>+Rp {refund_amt:,}</b> (Masuk Saldo)\n"
            f"• <b>Saldo Anda Sekarang:</b> <b>Rp {new_balance:,}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Saldo telah otomatis dikembalikan ke akun bot Anda."
        )
    elif plan_type == "payg":
        success_text += (
            f"• <b>Status PAYG:</b> <b>Berhenti Total (Auto-debet dinonaktifkan)</b>\n"
            f"• <b>Sisa Saldo Utama:</b> <b>Rp {new_balance:,}</b> (Aman)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Akun telah dihapus dari server dan tidak akan ada tagihan harian lagi."
        )
    else:
        success_text += (
            f"• <b>Status:</b> <b>Berhasil dihapus dari server</b>\n"
            f"• <b>Saldo Anda:</b> <b>Rp {new_balance:,}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
        )

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("📱 Lihat Akun Saya Lainnya", callback_data="menu_my_accounts"),
        types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home")
    )
    bot.edit_message_text(success_text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

# Server info
@bot.callback_query_handler(func=lambda call: call.data == "menu_server_info")
def callback_server_info(call):
    user_id = call.from_user.id
    domain = xray_manager.get_domain()
    
    uptime = "N/A"
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])
            uptime = str(datetime.timedelta(seconds=int(uptime_seconds)))
    except Exception:
        pass

    text = (
        f"📊 <b>INFORMASI SERVER TUNNELING</b>\n\n"
        f"🌐 <b>Domain:</b> <code>{domain}</code>\n"
        f"⏱️ <b>Uptime:</b> <code>{uptime}</code>\n"
        f"⚡ <b>Port Aktif:</b>\n"
        f"  • TLS / HTTPS : 443, 8443\n"
        f"  • Non-TLS / HTTP : 80, 8080, 8880\n"
        f"  • gRPC Service : vmess-grpc, vless-grpc, trojan-grpc\n"
        f"  • Shadowsocks : Port 443 (aes-128-gcm)\n\n"
        f"✅ <i>Semua protokol beroperasi optimal 24/7.</i>"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home"))
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

# Admin Panel
@bot.callback_query_handler(func=lambda call: call.data == "menu_admin")
def callback_admin_menu(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "Akses ditolak. Anda bukan admin.", show_alert=True)
        return

    text, markup = render_admin_panel(user_id)
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

# --- Dynamic Rules Management ---

@bot.callback_query_handler(func=lambda call: call.data == "admin_rules_menu")
def callback_admin_rules_menu(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        return

    text = get_rules_summary()
    text += "\n<i>Pilih pengaturan yang ingin diubah:</i>"

    markup = types.InlineKeyboardMarkup(row_width=2)
    b_ip = types.InlineKeyboardButton("🌐 Ubah Limit IP", callback_data="admin_rule_ip_menu")
    b_quota = types.InlineKeyboardButton("📦 Ubah Limit Kuota", callback_data="admin_rule_quota_menu")
    b_sus = types.InlineKeyboardButton("⏱️ Ubah Durasi Suspen", callback_data="admin_rule_suspend_menu")
    b_pr_m = types.InlineKeyboardButton("💵 Ubah Harga Bulanan", callback_data="admin_rule_price_monthly_prompt")
    b_pr_p = types.InlineKeyboardButton("⚡ Ubah Tarif PAYG", callback_data="admin_rule_price_payg_prompt")
    
    auto_s = cfg.get("AUTO_SUSPEND_ENABLED", 1)
    auto_text = "🛡️ Auto-Suspen: [ON]" if auto_s else "🛡️ Auto-Suspen: [OFF]"
    b_toggle = types.InlineKeyboardButton(auto_text, callback_data="admin_rule_toggle_autosuspend")
    b_back = types.InlineKeyboardButton("🔙 Panel Admin", callback_data="menu_admin")

    markup.add(b_ip, b_quota)
    markup.add(b_sus, b_toggle)
    markup.add(b_pr_m, b_pr_p)
    markup.add(b_back)
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_rule_ip_menu")
def callback_admin_rule_ip_menu(call):
    user_id = call.from_user.id
    cfg = load_config()
    cur = cfg.get("DEFAULT_IP_LIMIT", 1)

    text = f"🌐 <b>ATUR LIMIT IP DEFAULT PER AKUN</b>\n\nSaat ini: <b>{cur} IP</b>\nPilih batas IP baru:"
    markup = types.InlineKeyboardMarkup(row_width=3)
    b1 = types.InlineKeyboardButton("1 IP", callback_data="set_rule_ip_1")
    b2 = types.InlineKeyboardButton("2 IP", callback_data="set_rule_ip_2")
    b3 = types.InlineKeyboardButton("3 IP", callback_data="set_rule_ip_3")
    b4 = types.InlineKeyboardButton("4 IP", callback_data="set_rule_ip_4")
    b5 = types.InlineKeyboardButton("5 IP", callback_data="set_rule_ip_5")
    b_c = types.InlineKeyboardButton("✏️ Custom IP", callback_data="set_rule_ip_custom")
    b_back = types.InlineKeyboardButton("🔙 Kembali", callback_data="admin_rules_menu")

    markup.add(b1, b2, b3)
    markup.add(b4, b5, b_c)
    markup.add(b_back)
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_rule_ip_"))
def callback_set_rule_ip(call):
    user_id = call.from_user.id
    val_str = call.data.replace("set_rule_ip_", "")
    if val_str == "custom":
        user_states[user_id] = {"action": "wait_custom_rule_ip"}
        bot.send_message(user_id, "✏️ Masukkan angka Limit IP baru (contoh: <code>1</code>):", reply_markup=back_home_keyboard())
        return

    try:
        val = int(val_str)
        update_config_key("DEFAULT_IP_LIMIT", val)
        bot.answer_callback_query(call.id, f"Limit IP default berhasil diubah menjadi {val} IP!", show_alert=True)
        callback_admin_rules_menu(call)
    except Exception as e:
        bot.send_message(user_id, f"Gagal mengubah limit IP: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_rule_quota_menu")
def callback_admin_rule_quota_menu(call):
    user_id = call.from_user.id
    cfg = load_config()
    cur = cfg.get("DEFAULT_QUOTA_GB", 350)
    cur_str = f"{cur} GB" if cur > 0 else "Unlimited"

    text = f"📦 <b>ATUR LIMIT KUOTA DEFAULT PER AKUN</b>\n\nSaat ini: <b>{cur_str}</b>\nPilih batas kuota baru:"
    markup = types.InlineKeyboardMarkup(row_width=2)
    b1 = types.InlineKeyboardButton("100 GB", callback_data="set_rule_quota_100")
    b2 = types.InlineKeyboardButton("250 GB", callback_data="set_rule_quota_250")
    b3 = types.InlineKeyboardButton("350 GB", callback_data="set_rule_quota_350")
    b4 = types.InlineKeyboardButton("500 GB", callback_data="set_rule_quota_500")
    b5 = types.InlineKeyboardButton("Unlimited (0)", callback_data="set_rule_quota_0")
    b_c = types.InlineKeyboardButton("✏️ Custom GB", callback_data="set_rule_quota_custom")
    b_back = types.InlineKeyboardButton("🔙 Kembali", callback_data="admin_rules_menu")

    markup.add(b1, b2)
    markup.add(b3, b4)
    markup.add(b5, b_c)
    markup.add(b_back)
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_rule_quota_"))
def callback_set_rule_quota(call):
    user_id = call.from_user.id
    val_str = call.data.replace("set_rule_quota_", "")
    if val_str == "custom":
        user_states[user_id] = {"action": "wait_custom_rule_quota"}
        bot.send_message(user_id, "✏️ Masukkan angka Limit Kuota dalam GB (contoh: <code>350</code>, atau 0 untuk unlimited):", reply_markup=back_home_keyboard())
        return

    try:
        val = int(val_str)
        update_config_key("DEFAULT_QUOTA_GB", val)
        val_name = f"{val} GB" if val > 0 else "Unlimited"
        bot.answer_callback_query(call.id, f"Limit Kuota default berhasil diubah menjadi {val_name}!", show_alert=True)
        callback_admin_rules_menu(call)
    except Exception as e:
        bot.send_message(user_id, f"Gagal mengubah kuota: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_rule_suspend_menu")
def callback_admin_rule_suspend_menu(call):
    user_id = call.from_user.id
    cfg = load_config()
    cur = cfg.get("SUSPEND_DURATION_MINUTES", 10)

    text = f"⏱️ <b>ATUR DURASI SUSPEN PELANGGARAN</b>\n\nSaat ini: <b>{cur} Menit</b>\nPilih durasi sanksi off akun:"
    markup = types.InlineKeyboardMarkup(row_width=3)
    b1 = types.InlineKeyboardButton("5 Menit", callback_data="set_rule_suspend_5")
    b2 = types.InlineKeyboardButton("10 Menit", callback_data="set_rule_suspend_10")
    b3 = types.InlineKeyboardButton("15 Menit", callback_data="set_rule_suspend_15")
    b4 = types.InlineKeyboardButton("30 Menit", callback_data="set_rule_suspend_30")
    b5 = types.InlineKeyboardButton("60 Menit", callback_data="set_rule_suspend_60")
    b_c = types.InlineKeyboardButton("✏️ Custom", callback_data="set_rule_suspend_custom")
    b_back = types.InlineKeyboardButton("🔙 Kembali", callback_data="admin_rules_menu")

    markup.add(b1, b2, b3)
    markup.add(b4, b5, b_c)
    markup.add(b_back)
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_rule_suspend_"))
def callback_set_rule_suspend(call):
    user_id = call.from_user.id
    val_str = call.data.replace("set_rule_suspend_", "")
    if val_str == "custom":
        user_states[user_id] = {"action": "wait_custom_rule_suspend"}
        bot.send_message(user_id, "✏️ Masukkan durasi suspen dalam menit (contoh: <code>10</code>):", reply_markup=back_home_keyboard())
        return

    try:
        val = int(val_str)
        update_config_key("SUSPEND_DURATION_MINUTES", val)
        bot.answer_callback_query(call.id, f"Durasi suspen berhasil diset menjadi {val} Menit!", show_alert=True)
        callback_admin_rules_menu(call)
    except Exception as e:
        bot.send_message(user_id, f"Gagal mengubah durasi suspen: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "admin_rule_price_monthly_prompt")
def callback_admin_rule_price_monthly_prompt(call):
    user_id = call.from_user.id
    cfg = load_config()
    cur = cfg.get("PRICE_MONTHLY", 8000)
    user_states[user_id] = {"action": "wait_price_monthly"}
    text = (
        f"💵 <b>UBAH HARGA PAKET BULANAN (30 HARI)</b>\n\n"
        f"Harga Saat Ini: <b>Rp {cur:,}</b>\n\n"
        f"Ketik nominal harga baru (contoh: <code>10000</code>):"
    )
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "admin_rule_price_payg_prompt")
def callback_admin_rule_price_payg_prompt(call):
    user_id = call.from_user.id
    cfg = load_config()
    cur_d = cfg.get("PRICE_PAYG_DAILY", 300)
    cur_q = cfg.get("PRICE_PAYG_10GB", 1000)
    user_states[user_id] = {"action": "wait_price_payg"}
    text = (
        f"⚡ <b>UBAH TARIF PAY-AS-YOU-GO (PAYG)</b>\n\n"
        f"Tarif Harian Saat Ini     : <b>Rp {cur_d:,} / Hari</b>\n"
        f"Tarif Kuota 10GB Saat Ini : <b>Rp {cur_q:,} / 10GB</b>\n\n"
        f"Format masukan: <code>tarif_harian tarif_10gb</code>\n"
        f"Contoh: <code>500 1500</code>"
    )
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "admin_rule_toggle_autosuspend")
def callback_admin_rule_toggle_autosuspend(call):
    cfg = load_config()
    cur = cfg.get("AUTO_SUSPEND_ENABLED", 1)
    new_val = 0 if cur else 1
    update_config_key("AUTO_SUSPEND_ENABLED", new_val)
    status_str = "AKTIF" if new_val else "NONAKTIF"
    bot.answer_callback_query(call.id, f"Auto-Suspen Multi-Login sekarang {status_str}!", show_alert=True)
    callback_admin_rules_menu(call)

# --- Live User Monitoring & Management ---

@bot.callback_query_handler(func=lambda call: call.data == "admin_monitor_users")
def callback_admin_monitor_users(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        return

    active_sessions = xray_manager.get_active_sessions()
    suspended_accounts = database.get_locked_accounts()
    all_accs = database.get_all_vpn_accounts_detailed(limit=200)

    text = (
        f"👥 <b>MONITORING USER & KONEKSI LIVE</b>\n\n"
        f"📱 Total Akun Terdaftar : <b>{len(all_accs)}</b>\n"
        f"🟢 User Sedang Online  : <b>{len(active_sessions)} User</b>\n"
        f"🔒 Akun Disuspen/Lock  : <b>{len(suspended_accounts)} User</b>\n\n"
        f"Pilih kategori monitoring di bawah ini:"
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    b1 = types.InlineKeyboardButton(f"🟢 Lihat User Sedang Login ({len(active_sessions)})", callback_data="admin_users_active_login")
    b2 = types.InlineKeyboardButton(f"🔒 Lihat Akun Terkunci / Suspen ({len(suspended_accounts)})", callback_data="admin_list_suspended")
    b3 = types.InlineKeyboardButton("📋 Lihat Semua Akun VPN", callback_data="admin_users_all_vpn")
    b4 = types.InlineKeyboardButton("🔍 Cari Akun by Username", callback_data="admin_search_user_prompt")
    b_back = types.InlineKeyboardButton("🔙 Panel Admin", callback_data="menu_admin")
    
    markup.add(b1, b2, b3, b4, b_back)
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_users_active_login")
def callback_admin_users_active_login(call):
    user_id = call.from_user.id
    active_sessions = xray_manager.get_active_sessions()

    if not active_sessions:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Kembali", callback_data="admin_monitor_users"))
        bot.edit_message_text("🟢 <b>Tidak ada user yang sedang aktif login saat ini.</b>", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)
        return

    text = f"🟢 <b>USER SEDANG LOGIN AKTIF ({len(active_sessions)} User):</b>\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)

    for uname, ips in list(active_sessions.items())[:10]:
        usage = xray_manager.get_user_usage_and_status(uname)
        proto = usage["protocol"].upper()
        ip_sample = ", ".join(ips[:2])
        text += (
            f"• <b>{uname}</b> ({proto})\n"
            f"  IP ({len(ips)}/{usage['ip_limit']}): <code>{ip_sample}</code>\n"
            f"  Kuota: <b>{usage['used_human']} / {usage['quota_human']}</b> ({usage['percent']:.1f}%)\n"
            f"  Bar: <code>{usage['progress_bar']}</code>\n\n"
        )
        markup.add(types.InlineKeyboardButton(f"⚙️ Kelola {uname}", callback_data=f"manage_user_{uname}"))

    markup.add(types.InlineKeyboardButton("🔙 Kembali ke Monitor", callback_data="admin_monitor_users"))
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_list_suspended")
def callback_admin_list_suspended(call):
    user_id = call.from_user.id
    locked = database.get_locked_accounts()

    if not locked:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Kembali", callback_data="admin_monitor_users"))
        bot.edit_message_text("🔒 <b>Tidak ada akun yang sedang disuspen / terkunci saat ini.</b>", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)
        return

    text = f"🔒 <b>DAFTAR AKUN DISUSPEN / TERKUNCI ({len(locked)} Total):</b>\n\n"
    markup = types.InlineKeyboardMarkup(row_width=2)

    for acc in locked[:10]:
        uname = acc["vpn_username"]
        proto = acc["protocol"]
        reason = acc.get("lock_reason", "multi_login")
        usage = xray_manager.get_user_usage_and_status(uname, proto)
        rem_str = usage.get("remaining_human", "Selesai")

        text += (
            f"🔴 <b>{uname}</b> ({proto.upper()})\n"
            f"  Alasan : <code>{reason}</code>\n"
            f"  Sisa Waktu : <b>{rem_str}</b>\n\n"
        )
        b_unban = types.InlineKeyboardButton(f"🔓 Unban {uname}", callback_data=f"quick_unban_{uname}")
        b_det = types.InlineKeyboardButton(f"⚙️ Detail", callback_data=f"manage_user_{uname}")
        markup.add(b_unban, b_det)

    markup.add(types.InlineKeyboardButton("🔙 Kembali ke Monitor", callback_data="admin_monitor_users"))
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("quick_unban_"))
def callback_quick_unban(call):
    uname = call.data.replace("quick_unban_", "")
    acc = database.get_account_by_username(uname)
    proto = acc.get("protocol", "vmess") if acc else "vmess"
    xray_manager.unsuspend_account(proto, uname)
    bot.answer_callback_query(call.id, f"Akun {uname} berhasil di-unban / diaktifkan!", show_alert=True)
    callback_admin_list_suspended(call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_users_all_vpn")
def callback_admin_users_all_vpn(call):
    user_id = call.from_user.id
    accounts = database.get_all_vpn_accounts_detailed(limit=25)

    if not accounts:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Kembali", callback_data="admin_monitor_users"))
        bot.edit_message_text("Belum ada akun VPN yang dibuat.", chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)
        return

    text = f"📋 <b>SEMUA AKUN VPN ({len(accounts)} Ditampilkan):</b>\n\n"
    markup = types.InlineKeyboardMarkup(row_width=2)
    for acc in accounts:
        status_icon = "🟢" if acc["status"] == "active" else "🔴"
        uname = acc["vpn_username"]
        btn_text = f"{status_icon} {uname} ({acc['protocol']})"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"manage_user_{uname}"))

    markup.add(types.InlineKeyboardButton("🔙 Kembali", callback_data="admin_monitor_users"))
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_search_user_prompt")
def callback_admin_search_user_prompt(call):
    user_id = call.from_user.id
    user_states[user_id] = {"action": "wait_search_vpn_user"}
    text = "🔍 <b>CARI AKUN VPN</b>\n\nMasukkan username VPN yang ingin dicari:"
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

# --- Single User Control Dashboard ---

@bot.callback_query_handler(func=lambda call: call.data.startswith("manage_user_"))
def callback_manage_user(call):
    user_id = call.from_user.id
    uname = call.data.replace("manage_user_", "")
    acc = database.get_account_by_username(uname)

    if not acc:
        bot.answer_callback_query(call.id, f"Akun {uname} tidak ditemukan!", show_alert=True)
        return

    proto = acc["protocol"]
    usage = xray_manager.get_user_usage_and_status(uname, proto)
    status_str = "🟢 AKTIF" if not usage["is_locked"] else f"🔴 TERKUNCI ({usage.get('lock_reason', '')})"
    plan_type = str(acc.get("plan_type", "")).lower()
    raw_exp = str(acc.get("exp_date", ""))
    exp_display = "⚡ PAYG (Auto-Debet Harian)" if (plan_type == "payg" or raw_exp.upper() == "PAYG") else (raw_exp or "-")

    text = (
        f"👤 <b>KONTROL PENGGUNA: {uname}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"» Protokol     : <b>{proto.upper()}</b>\n"
        f"» Paket        : <b>{acc['plan_type'].upper()}</b>\n"
        f"» Pemilik TG   : <code>{tg_user}</code>\n"
        f"» Status Akun  : <b>{status_str}</b>\n"
        f"» Masa Aktif   : <code>{exp_display}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>KUOTA & TRAFIK:</b>\n"
        f"» Terpakai     : <b>{usage['used_human']} / {usage['quota_human']}</b>\n"
        f"» Persentase   : <b>{usage['percent']:.1f}%</b>\n"
        f"» Bar Visual   : <code>{usage['progress_bar']}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>KONEKSI IP:</b>\n"
        f"» Batas Login  : <b>{usage['ip_limit']} IP</b>\n"
        f"» Aktif Saat Ini: <b>{usage['active_ip_count']} IP</b>\n"
    )
    if usage["active_ips"]:
        text += f"» IP Terhubung : <code>{', '.join(usage['active_ips'])}</code>\n"

    if usage["is_locked"]:
        text += (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⏱️ <b>INFO SUSPEN:</b>\n"
            f"» Hingga Waktu : <code>{usage.get('locked_until')}</code>\n"
            f"» Sisa Hitung  : <b>{usage.get('remaining_human')}</b>\n"
        )

    markup = types.InlineKeyboardMarkup(row_width=2)
    if usage["is_locked"]:
        b_lock = types.InlineKeyboardButton("🔓 Buka Kunci (Unban)", callback_data=f"user_act_unsuspend_{uname}")
    else:
        b_lock = types.InlineKeyboardButton("🔒 Suspen Akun", callback_data=f"user_act_suspend_{uname}")

    b_reset = types.InlineKeyboardButton("🔄 Reset Kuota", callback_data=f"user_act_resetquota_{uname}")
    b_quota = types.InlineKeyboardButton("✏️ Atur Kuota", callback_data=f"user_act_setquota_prompt_{uname}")
    b_ip = types.InlineKeyboardButton("✏️ Atur Limit IP", callback_data=f"user_act_setip_prompt_{uname}")
    b_del = types.InlineKeyboardButton("🗑️ Hapus Akun", callback_data=f"user_act_delconfirm_{uname}")
    b_back = types.InlineKeyboardButton("🔙 Monitoring User", callback_data="admin_monitor_users")

    markup.add(b_lock, b_reset)
    markup.add(b_quota, b_ip)
    markup.add(b_del)
    markup.add(b_back)

    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_act_unsuspend_"))
def callback_user_act_unsuspend(call):
    uname = call.data.replace("user_act_unsuspend_", "")
    acc = database.get_account_by_username(uname)
    proto = acc.get("protocol", "vmess") if acc else "vmess"
    xray_manager.unsuspend_account(proto, uname)
    bot.answer_callback_query(call.id, f"Akun {uname} berhasil dipulihkan & aktif kembali!", show_alert=True)
    call.data = f"manage_user_{uname}"
    callback_manage_user(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_act_suspend_"))
def callback_user_act_suspend(call):
    uname = call.data.replace("user_act_suspend_", "")
    acc = database.get_account_by_username(uname)
    proto = acc.get("protocol", "vmess") if acc else "vmess"
    cfg = load_config()
    suspend_min = cfg.get("SUSPEND_DURATION_MINUTES", 10)
    xray_manager.suspend_account(proto, uname, duration_minutes=suspend_min, reason="admin_manual")
    bot.answer_callback_query(call.id, f"Akun {uname} disuspen selama {suspend_min} Menit.", show_alert=True)
    call.data = f"manage_user_{uname}"
    callback_manage_user(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_act_resetquota_"))
def callback_user_act_resetquota(call):
    uname = call.data.replace("user_act_resetquota_", "")
    acc = database.get_account_by_username(uname)
    proto = acc.get("protocol", "vmess") if acc else "vmess"
    xray_manager.reset_user_quota(proto, uname)
    bot.answer_callback_query(call.id, f"Pemakaian kuota {uname} berhasil di-reset ke 0!", show_alert=True)
    call.data = f"manage_user_{uname}"
    callback_manage_user(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_act_setquota_prompt_"))
def callback_user_act_setquota_prompt(call):
    user_id = call.from_user.id
    uname = call.data.replace("user_act_setquota_prompt_", "")
    user_states[user_id] = {"action": "wait_user_custom_quota", "uname": uname}
    text = f"✏️ <b>UBAH LIMIT KUOTA UNTUK {uname}</b>\n\nMasukkan kuota baru dalam GB (contoh: <code>350</code>, atau <code>0</code> untuk unlimited):"
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_act_setip_prompt_"))
def callback_user_act_setip_prompt(call):
    user_id = call.from_user.id
    uname = call.data.replace("user_act_setip_prompt_", "")
    user_states[user_id] = {"action": "wait_user_custom_ip", "uname": uname}
    text = f"✏️ <b>UBAH LIMIT IP UNTUK {uname}</b>\n\nMasukkan batas IP baru (contoh: <code>1</code>):"
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_act_delconfirm_"))
def callback_user_act_delconfirm(call):
    user_id = call.from_user.id
    uname = call.data.replace("user_act_delconfirm_", "")
    text = f"⚠️ <b>KONFIRMASI PENGHAPUSAN</b>\n\nApakah Anda yakin ingin menghapus akun <code>{uname}</code> secara permanen?"
    markup = types.InlineKeyboardMarkup()
    b_yes = types.InlineKeyboardButton("🗑️ Ya, Hapus Sekarang", callback_data=f"user_act_delete_{uname}")
    b_no = types.InlineKeyboardButton("❌ Batal", callback_data=f"manage_user_{uname}")
    markup.add(b_yes, b_no)
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("user_act_delete_"))
def callback_user_act_delete(call):
    uname = call.data.replace("user_act_delete_", "")
    acc = database.get_account_by_username(uname)
    proto = acc.get("protocol", "vmess") if acc else "vmess"
    xray_manager.delete_account(proto, uname)
    database.delete_vpn_account_by_username(uname)
    bot.answer_callback_query(call.id, f"Akun {uname} telah berhasil dihapus permanen.", show_alert=True)
    callback_admin_monitor_users(call)

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
def callback_admin_broadcast(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        return

    user_states[user_id] = {"action": "wait_broadcast"}
    text = "📢 <b>BROADCAST PESAN KE SEMUA PENGGUNA</b>\n\nKetik pesan broadcast yang ingin dikirim:"
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "admin_addsaldo_prompt")
def callback_admin_addsaldo_prompt(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        return

    user_states[user_id] = {"action": "wait_addsaldo"}
    text = "➕ <b>TAMBAH SALDO PENGGUNA</b>\n\nFormat: <code>user_id jumlah</code>\nContoh: <code>123456789 20000</code>"
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "admin_list_users")
def callback_admin_list_users(call):
    user_id = call.from_user.id
    if not is_admin(user_id):
        return

    users = database.get_all_users()
    text = f"👥 <b>DAFTAR PENGGUNA ({len(users)} Total):</b>\n\n"
    for u in users[:25]:
        uname = f"@{u['username']}" if u['username'] else u['first_name']
        text += f"• <code>{u['user_id']}</code> | {uname} | Rp {u['balance']:,}\n"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Panel Admin", callback_data="menu_admin"))
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

# Back to main menu
@bot.callback_query_handler(func=lambda call: call.data == "menu_home")
def callback_home(call):
    user_id = call.from_user.id
    u = database.get_user(user_id)
    bal = u["balance"] if u else 0
    first_name = call.from_user.first_name
    domain = xray_manager.get_domain()

    text = (
        f"👋 <b>Halo, {first_name}!</b>\n\n"
        f"Selamat datang di <b>SATSET Tunneling Store</b>.\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Info Pengguna:</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💰 Saldo: <b>Rp {bal:,}</b>\n"
        f"🌐 Host/Domain: <code>{domain}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Silakan pilih menu di bawah ini:"
    )
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=main_menu_keyboard(user_id))

# Text handler for input prompts
@bot.message_handler(func=lambda msg: True, content_types=['text'])
def handle_text_inputs(message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    state = user_states.get(user_id)
    if not state:
        return

    action = state.get("action")

    # Custom topup amount
    if action == "wait_custom_topup":
        del user_states[user_id]
        try:
            amt = int(text)
            initiate_qris_payment(user_id, amt)
        except ValueError:
            bot.send_message(user_id, "Masukkan hanya angka nominal valid (contoh: 15000).")

    # Monthly package username input
    elif action == "wait_username_monthly":
        proto = state["proto"]
        price = state["price"]
        del user_states[user_id]

        if not re_valid_username(text):
            bot.send_message(user_id, "❌ Username hanya boleh berisi huruf dan angka (3-15 karakter), tanpa simbol atau spasi.")
            return

        if xray_manager.username_exists(text):
            bot.send_message(user_id, "❌ Username ini sudah digunakan di server. Silakan coba username lain.")
            return

        # Deduct balance
        if not database.deduct_balance(user_id, price):
            bot.send_message(user_id, "❌ Saldo Anda tidak mencukupi.")
            return

        wait_msg = bot.send_message(user_id, f"⏳ <i>Membuat akun {proto.upper()} untuk {text}...</i>")
        try:
            cfg = load_config()
            q_gb = cfg.get("DEFAULT_QUOTA_GB", 350)
            ip_l = cfg.get("DEFAULT_IP_LIMIT", 1)
            acc = xray_manager.create_account(proto, text, days=30, quota_gb=q_gb, ip_limit=ip_l)
            database.add_vpn_account(user_id, proto, text, acc["uuid"], "monthly", acc["exp_date"], acc["primary_link"], quota_gb=q_gb, ip_limit=ip_l, price_paid=price)
            bot.delete_message(user_id, wait_msg.message_id)
            send_account_details(user_id, acc, title=f"🎉 AKUN {proto.upper()} 30 HARI BERHASIL DIBUAT")
        except Exception as e:
            # Refund if failed
            database.add_balance(user_id, price)
            bot.send_message(user_id, f"❌ Terjadi kesalahan: {e}. Saldo Anda telah dikembalikan.")

    # PAYG username input
    elif action == "wait_username_payg":
        proto = state["proto"]
        daily_price = state["daily_price"]
        del user_states[user_id]

        if not re_valid_username(text):
            bot.send_message(user_id, "❌ Username hanya boleh berisi huruf dan angka (3-15 karakter), tanpa simbol atau spasi.")
            return

        if xray_manager.username_exists(text):
            bot.send_message(user_id, "❌ Username ini sudah digunakan di server. Silakan coba username lain.")
            return

        # Deduct initial day fee
        if not database.deduct_balance(user_id, daily_price):
            bot.send_message(user_id, "❌ Saldo Anda tidak mencukupi untuk biaya hari pertama.")
            return

        wait_msg = bot.send_message(user_id, f"⏳ <i>Mengaktifkan langganan PAYG {proto.upper()}...</i>")
        try:
            cfg = load_config()
            q_gb = cfg.get("DEFAULT_QUOTA_GB", 350)
            ip_l = cfg.get("DEFAULT_IP_LIMIT", 1)
            acc = xray_manager.create_account(proto, text, days=3650, quota_gb=q_gb, ip_limit=ip_l)
            database.add_vpn_account(user_id, proto, text, acc["uuid"], "payg", "PAYG", acc["primary_link"], quota_gb=q_gb, ip_limit=ip_l, price_paid=daily_price)
            database.add_payg_subscription(user_id, text, proto, "daily")
            acc["plan_type"] = "payg"
            acc["exp_human"] = "⚡ Aktif Selama Saldo Cukup (PAYG Harian)"
            bot.delete_message(user_id, wait_msg.message_id)
            send_account_details(user_id, acc, title=f"⚡ AKUN PAYG {proto.upper()} AKTIF")
        except Exception as e:
            database.add_balance(user_id, daily_price)
            bot.send_message(user_id, f"❌ Terjadi kesalahan: {e}. Saldo dikembalikan.")

    # Broadcast message (admin)
    elif action == "wait_broadcast":
        del user_states[user_id]
        users = database.get_all_users()
        sent = 0
        wait_msg = bot.send_message(user_id, f"⏳ <i>Mengirim broadcast ke {len(users)} pengguna...</i>")
        for u in users:
            try:
                bot.send_message(u["user_id"], f"📢 <b>PENGUMUMAN RESMI</b>\n\n{text}")
                sent += 1
                time.sleep(0.05)
            except Exception:
                pass
        bot.edit_message_text(f"✅ Broadcast selesai! Berhasil terkirim ke {sent} pengguna.", chat_id=user_id, message_id=wait_msg.message_id)

    # Add saldo (admin)
    elif action == "wait_addsaldo":
        del user_states[user_id]
        parts = text.split()
        if len(parts) != 2:
            bot.send_message(user_id, "Format salah. Gunakan: <code>user_id jumlah</code>")
            return
        target_uid, amount = parts[0], parts[1]
        try:
            target_uid = int(target_uid)
            amount = int(amount)
            new_bal = database.add_balance(target_uid, amount)
            bot.send_message(user_id, f"✅ Berhasil menambahkan Rp {amount:,} ke user {target_uid}. Saldo sekarang: Rp {new_bal:,}")
            try:
                bot.send_message(target_uid, f"🎉 <b>Saldo Anda Ditambahkan Admin!</b>\nJumlah: Rp {amount:,}\nSaldo Sekarang: Rp {new_bal:,}")
            except Exception:
                pass
        except ValueError:
            bot.send_message(user_id, "ID dan Jumlah harus berupa angka.")

    # Custom rule IP
    elif action == "wait_custom_rule_ip":
        del user_states[user_id]
        m = re.search(r'\d+', text)
        if m:
            val = int(m.group())
            update_config_key("DEFAULT_IP_LIMIT", val)
            bot.send_message(user_id, f"✅ Limit IP default berhasil diset ke <b>{val} IP</b>.\n\n" + get_rules_summary(), reply_markup=main_menu_keyboard(user_id))
        else:
            bot.send_message(user_id, "Masukkan angka yang valid (contoh: 1 atau 2).")

    # Custom rule Quota
    elif action == "wait_custom_rule_quota":
        del user_states[user_id]
        if "unlimited" in text.lower():
            val = 0
        else:
            m = re.search(r'\d+', text)
            val = int(m.group()) if m else -1
            
        if val >= 0:
            update_config_key("DEFAULT_QUOTA_GB", val)
            v_name = f"{val} GB" if val > 0 else "Unlimited"
            bot.send_message(user_id, f"✅ Limit Kuota default berhasil diset ke <b>{v_name}</b>.\n\n" + get_rules_summary(), reply_markup=main_menu_keyboard(user_id))
        else:
            bot.send_message(user_id, "Masukkan angka kuota yang valid dalam GB (contoh: 350) atau ketik 'unlimited'.")

    # Custom rule Suspend
    elif action == "wait_custom_rule_suspend":
        del user_states[user_id]
        m = re.search(r'\d+', text)
        if m:
            val = int(m.group())
            update_config_key("SUSPEND_DURATION_MINUTES", val)
            bot.send_message(user_id, f"✅ Durasi suspen berhasil diset ke <b>{val} Menit</b>.\n\n" + get_rules_summary(), reply_markup=main_menu_keyboard(user_id))
        else:
            bot.send_message(user_id, "Masukkan angka menit yang valid (contoh: 10).")

    # Change monthly price
    elif action == "wait_price_monthly":
        del user_states[user_id]
        clean_text = text.replace(".", "").replace(",", "")
        m = re.search(r'\d+', clean_text)
        if m:
            val = int(m.group())
            update_config_key("PRICE_MONTHLY", val)
            bot.send_message(user_id, f"✅ Harga paket bulanan berhasil diubah menjadi <b>Rp {val:,} / 30 Hari</b>.\n\n" + get_rules_summary(), reply_markup=main_menu_keyboard(user_id))
        else:
            bot.send_message(user_id, "Masukkan nominal harga yang valid (contoh: 8000).")

    # Change PAYG price
    elif action == "wait_price_payg":
        del user_states[user_id]
        nums = [int(x) for x in re.findall(r'\d+', text.replace(".", "").replace(",", ""))]
        if len(nums) >= 2:
            d_val = nums[0]
            q_val = nums[1]
            update_config_key("PRICE_PAYG_DAILY", d_val)
            update_config_key("PRICE_PAYG_10GB", q_val)
            bot.send_message(user_id, f"✅ Tarif PAYG berhasil diperbarui:\n• Harian: Rp {d_val:,}\n• Kuota 10GB: Rp {q_val:,}\n\n" + get_rules_summary(), reply_markup=main_menu_keyboard(user_id))
        else:
            bot.send_message(user_id, "Format salah. Masukkan dua angka, contoh: <code>300 1000</code> (tarif harian tarif kuota 10gb)")

    # Search user
    elif action == "wait_search_vpn_user":
        del user_states[user_id]
        acc = database.get_account_by_username(text)
        if not acc:
            bot.send_message(user_id, f"❌ Akun dengan username <code>{text}</code> tidak ditemukan.", reply_markup=main_menu_keyboard(user_id))
            return
        proto = acc["protocol"]
        usage = xray_manager.get_user_usage_and_status(text, proto)
        status_str = "🟢 AKTIF" if not usage["is_locked"] else f"🔴 TERKUNCI ({usage.get('lock_reason', '')})"
        plan_type = str(acc.get("plan_type", "")).lower()
        raw_exp = str(acc.get("exp_date", ""))
        exp_display = "⚡ PAYG (Auto-Debet)" if (plan_type == "payg" or raw_exp.upper() == "PAYG") else (raw_exp or "-")
        card_text = (
            f"👤 <b>KONTROL PENGGUNA: {text}</b>\n"
            f"» Protokol: <b>{proto.upper()}</b> | Paket: <b>{acc['plan_type'].upper()}</b>\n"
            f"» Status: <b>{status_str}</b> | Expired: <code>{exp_display}</code>\n"
            f"» Kuota: <b>{usage['used_human']} / {usage['quota_human']}</b> ({usage['percent']:.1f}%)\n"
            f"» Batas IP: <b>{usage['ip_limit']} IP</b> | Aktif: <b>{usage['active_ip_count']} IP</b>"
        )
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(types.InlineKeyboardButton(f"⚙️ Buka Menu Kelola Lengkap", callback_data=f"manage_user_{text}"))
        markup.add(types.InlineKeyboardButton("🔙 Panel Admin", callback_data="menu_admin"))
        bot.send_message(user_id, card_text, reply_markup=markup)

    # Set user custom quota
    elif action == "wait_user_custom_quota":
        uname = state["uname"]
        del user_states[user_id]
        try:
            val = int(text)
            acc = database.get_account_by_username(uname)
            proto = acc.get("protocol", "vmess") if acc else "vmess"
            xray_manager.set_user_quota(proto, uname, val)
            val_name = f"{val} GB" if val > 0 else "Unlimited"
            bot.send_message(user_id, f"✅ Kuota untuk akun <code>{uname}</code> berhasil diatur menjadi {val_name}.", reply_markup=main_menu_keyboard(user_id))
        except ValueError:
            bot.send_message(user_id, "Masukkan angka yang valid.")

    # Set user custom IP limit
    elif action == "wait_user_custom_ip":
        uname = state["uname"]
        del user_states[user_id]
        try:
            val = int(text)
            acc = database.get_account_by_username(uname)
            proto = acc.get("protocol", "vmess") if acc else "vmess"
            xray_manager.set_user_ip_limit(proto, uname, val)
            bot.send_message(user_id, f"✅ Limit IP untuk akun <code>{uname}</code> berhasil diatur menjadi {val} IP.", reply_markup=main_menu_keyboard(user_id))
        except ValueError:
            bot.send_message(user_id, "Masukkan angka yang valid.")

def re_valid_username(u: str) -> bool:
    import re
    return bool(re.match(r"^[a-zA-Z0-9_]{3,15}$", u))

def send_account_details(user_id: int, acc: dict, title: str):
    domain = acc.get("domain") or xray_manager.get_domain()
    proto = acc["protocol"].upper()
    uname = acc.get("username") or acc.get("vpn_username", "")
    uuid_str = acc.get("uuid", "")
    plan_type = str(acc.get("plan_type", "")).lower()
    raw_exp = str(acc.get("exp_date", ""))
    if plan_type == "payg" or raw_exp.upper() == "PAYG" or "PAYG" in title.upper():
        exp_h = "⚡ Aktif Selama Saldo Cukup (PAYG Harian)"
    else:
        exp_h = acc.get("exp_human", acc.get("exp_date", ""))
        
    if acc["protocol"].lower() in ["ssh", "openssh", "dropbear"]:
        ip_srv = acc.get("ip_server", domain)
        pwd = acc.get("password", uuid_str)
        payload = acc.get("payload_ws", f"GET / HTTP/1.1[crlf]Host: {domain}[crlf]Upgrade: websocket[crlf][crlf]")
        text = (
            f"<b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Username      :</b> <code>{uname}</code>\n"
            f"<b>Password      :</b> <code>{pwd}</code>\n"
            f"<b>Domain / Host :</b> <code>{domain}</code>\n"
            f"<b>IP Server     :</b> <code>{ip_srv}</code>\n"
            f"<b>Port OpenSSH  :</b> <code>22</code>\n"
            f"<b>Port Dropbear :</b> <code>109, 143</code>\n"
            f"<b>Port SSL/TLS  :</b> <code>443, 777</code>\n"
            f"<b>Port WS NonTLS:</b> <code>80, 8080, 8880</code>\n"
            f"<b>Port WS TLS   :</b> <code>443, 8443</code>\n"
            f"<b>BadVPN UDP GW :</b> <code>7100, 7200, 7300</code>\n"
            f"<b>Masa Aktif    :</b> <code>{exp_h}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Payload WebSocket:</b>\n"
            f"<code>{payload}</code>\n"
        )
    else:
        text = (
            f"<b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>Remarks / User:</b> <code>{uname}</code>\n"
            f"<b>Protokol      :</b> <code>{proto}</code>\n"
            f"<b>Domain / Host :</b> <code>{domain}</code>\n"
            f"<b>Port TLS      :</b> <code>443, 8443</code>\n"
            f"<b>Port Non-TLS  :</b> <code>80, 8080, 8880</code>\n"
            f"<b>UUID / Key    :</b> <code>{uuid_str}</code>\n"
            f"<b>Masa Aktif    :</b> <code>{exp_h}</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>LINK CONFIG:</b>\n"
        )

        if acc.get("link_tls"):
            text += f"\n<b>TLS (Port 443):</b>\n<code>{acc['link_tls']}</code>\n"
        if acc.get("link_ntls"):
            text += f"\n<b>Non-TLS (Port 80):</b>\n<code>{acc['link_ntls']}</code>\n"
        if acc.get("link_grpc"):
            text += f"\n<b>gRPC (Port 443):</b>\n<code>{acc['link_grpc']}</code>\n"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home"))
    bot.send_message(user_id, text, reply_markup=markup)

def main():
    logger.info("Starting SATSET Telegram Store Bot...")
    # Initialize database
    database.init_db()

    # Start background worker for Pakasir auto-crediting and PAYG midnight deduction
    payg_worker.start_background_worker(bot)

    # Start bot polling
    logger.info("Bot is polling for updates...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=15)
        except Exception as e:
            logger.error(f"Polling crashed with error: {e}. Restarting in 5s...")
            time.sleep(5)

if __name__ == "__main__":
    main()

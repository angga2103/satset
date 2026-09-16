import os
import sys
import io
import time
import uuid
import datetime
import logging
import telebot
from telebot import types

import qrcode
from config import load_config, save_config
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
    cfg = load_config()
    admin_id = str(cfg.get("ADMIN_ID", ""))
    if str(user_id) == admin_id:
        b_admin = types.InlineKeyboardButton("🛠️ Admin Panel", callback_data="menu_admin")
        markup.add(b_admin)
        
    return markup

def back_home_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home"))
    return markup

# --- Handlers ---

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
    
    text = (
        f"👋 <b>Halo, {first_name}!</b>\n\n"
        f"Selamat datang di <b>SATSET Tunneling Store</b>.\n"
        f"Layanan VPN Premium berkecepatan tinggi dengan berbagai protokol modern.\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Info Pengguna:</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
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
    database.create_transaction(order_id, user_id, amount, qr_url, qr_string)

    markup = types.InlineKeyboardMarkup(row_width=1)
    b_check = types.InlineKeyboardButton("🔄 Cek Status Pembayaran", callback_data=f"check_tx_{order_id}")
    b_cancel = types.InlineKeyboardButton("❌ Batalkan", callback_data="menu_home")
    markup.add(b_check, b_cancel)

    caption = (
        f"🧾 <b>INVOICE PEMBAYARAN QRIS</b>\n\n"
        f"Order ID: <code>{order_id}</code>\n"
        f"Jumlah Pembayaran: <b>Rp {amount:,}</b>\n"
        f"Metode: <b>QRIS Real-Time</b>\n\n"
        f"📌 <b>Cara Pembayaran:</b>\n"
        f"1. Simpan/Screenshot gambar QR Code di atas\n"
        f"2. Buka aplikasi M-Banking atau E-Wallet (Dana, OVO, Gopay, BCA, dll)\n"
        f"3. Pilih menu <b>Scan QRIS</b> dan upload gambar barcode\n"
        f"4. Selesaikan pembayaran\n"
        f"5. Saldo akan otomatis masuk dalam beberapa detik!"
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
    
    wait_msg = bot.send_message(user_id, f"⏳ <i>Membuat akun Trial {proto.upper()}...</i>")
    try:
        acc = xray_manager.create_account(proto, uname, days=1, quota_gb=0, ip_limit=2)
        database.add_vpn_account(user_id, proto, uname, acc["uuid"], "trial", acc["exp_date"], acc["primary_link"])
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

@bot.callback_query_handler(func=lambda call: call.data.startswith("detail_acc_"))
def callback_account_detail(call):
    user_id = call.from_user.id
    acc_id = int(call.data.replace("detail_acc_", ""))
    accounts = database.get_user_vpn_accounts(user_id)
    acc = next((a for a in accounts if a["id"] == acc_id), None)

    if not acc:
        bot.answer_callback_query(call.id, "Akun tidak ditemukan.", show_alert=True)
        return

    domain = xray_manager.get_domain()
    proto = acc['protocol'].upper()
    uname = acc['vpn_username']
    pwd = acc['uuid']

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
            f"Paket         : <b>{acc['plan_type'].upper()}</b>\n"
            f"Expired       : <b>{acc['exp_date']}</b>\n\n"
            f"🔗 <b>Payload WebSocket:</b>\n"
            f"<code>{payload}</code>"
        )
    else:
        text = (
            f"📱 <b>DETAIL AKUN VPN</b>\n\n"
            f"Protokol: <b>{proto}</b>\n"
            f"Username: <code>{uname}</code>\n"
            f"UUID / Password: <code>{pwd}</code>\n"
            f"Paket: <b>{acc['plan_type'].upper()}</b>\n"
            f"Expired: <b>{acc['exp_date']}</b>\n"
            f"Domain: <code>{domain}</code>\n\n"
            f"🔗 <b>Config Link:</b>\n"
            f"<code>{acc['config_link']}</code>"
        )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Kembali ke Daftar Akun", callback_data="menu_my_accounts"))
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

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
    cfg = load_config()
    if str(user_id) != str(cfg.get("ADMIN_ID", "")):
        bot.answer_callback_query(call.id, "Akses ditolak. Anda bukan admin.", show_alert=True)
        return

    stats = database.get_total_stats()
    text = (
        f"🛠️ <b>ADMINISTRATOR PANEL</b>\n\n"
        f"👥 Total Pengguna: <b>{stats['users']}</b>\n"
        f"📱 Total Akun Dibuat: <b>{stats['accounts']}</b>\n"
        f"💰 Total Pendapatan: <b>Rp {stats['revenue']:,}</b>\n\n"
        f"Pilih tindakan admin:"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    b1 = types.InlineKeyboardButton("📢 Broadcast Pesan", callback_data="admin_broadcast")
    b2 = types.InlineKeyboardButton("➕ Tambah Saldo User", callback_data="admin_addsaldo_prompt")
    b3 = types.InlineKeyboardButton("👥 List Users", callback_data="admin_list_users")
    b_back = types.InlineKeyboardButton("🔙 Menu Utama", callback_data="menu_home")
    markup.add(b1, b2)
    markup.add(b3)
    markup.add(b_back)
    bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_broadcast")
def callback_admin_broadcast(call):
    user_id = call.from_user.id
    cfg = load_config()
    if str(user_id) != str(cfg.get("ADMIN_ID", "")):
        return

    user_states[user_id] = {"action": "wait_broadcast"}
    text = "📢 <b>BROADCAST PESAN KE SEMUA PENGGUNA</b>\n\nKetik pesan broadcast yang ingin dikirim:"
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "admin_addsaldo_prompt")
def callback_admin_addsaldo_prompt(call):
    user_id = call.from_user.id
    cfg = load_config()
    if str(user_id) != str(cfg.get("ADMIN_ID", "")):
        return

    user_states[user_id] = {"action": "wait_addsaldo"}
    text = "➕ <b>TAMBAH SALDO PENGGUNA</b>\n\nFormat: <code>user_id jumlah</code>\nContoh: <code>123456789 20000</code>"
    bot.send_message(user_id, text, reply_markup=back_home_keyboard())

@bot.callback_query_handler(func=lambda call: call.data == "admin_list_users")
def callback_admin_list_users(call):
    user_id = call.from_user.id
    cfg = load_config()
    if str(user_id) != str(cfg.get("ADMIN_ID", "")):
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
            acc = xray_manager.create_account(proto, text, days=30, quota_gb=0, ip_limit=2)
            database.add_vpn_account(user_id, proto, text, acc["uuid"], "monthly", acc["exp_date"], acc["primary_link"])
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
            acc = xray_manager.create_account(proto, text, days=60, quota_gb=0, ip_limit=2)
            database.add_vpn_account(user_id, proto, text, acc["uuid"], "payg", acc["exp_date"], acc["primary_link"])
            database.add_payg_subscription(user_id, text, proto, "daily")
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

def re_valid_username(u: str) -> bool:
    import re
    return bool(re.match(r"^[a-zA-Z0-9_]{3,15}$", u))

def send_account_details(user_id: int, acc: dict, title: str):
    domain = acc.get("domain") or xray_manager.get_domain()
    proto = acc["protocol"].upper()
    uname = acc["username"]
    uuid_str = acc["uuid"]
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

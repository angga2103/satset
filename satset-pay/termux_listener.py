#!/usr/bin/env python3
"""
===================================================================
SATSET-PAY: Termux Android Push Notification Listener Daemon
===================================================================
Berjalan di aplikasi Termux (Android) tanpa iklan, tanpa limit,
dan langsung menangkap notifikasi uang masuk (GoBiz, Shopee, DANA, Bank)
lalu meneruskannya seketika ke server VPS SATSET-PAY.

Prasyarat di HP Android:
1. Termux App (disarankan unduh dari F-Droid / GitHub)
2. Termux:API App (dari F-Droid / GitHub)
3. Izin Akses Notifikasi diaktifkan untuk Termux:API
===================================================================
"""

import os
import sys
import time
import json
import subprocess
import hashlib
from datetime import datetime

# Fallback ke urllib jika requests belum diinstall
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False

CONFIG_FILE = os.path.expanduser("~/.satset_pay_config.json")
SEEN_FILE = os.path.expanduser("~/.satset_pay_seen.json")
DEFAULT_VPS_URL = "http://103.247.10.111:8088/api/v1/webhook/listener"

# Keyword deteksi transaksi pembayaran
TARGET_KEYWORDS = [
    "gopay", "gobiz", "shopee", "dana", "pembayaran",
    "diterima", "berhasil", "transfer", "uang masuk",
    "kredit", "cr", "rp", "idr"
]

TARGET_PACKAGES = [
    "com.gojek.merchant",       # GoBiz Merchant
    "com.gojek.gofood.merchant",
    "com.gojek.app",            # GoPay Personal
    "com.shopee.id",            # Shopee
    "com.shopeepay.merchant",   # Shopee Partner
    "id.dana",                  # DANA
    "com.telkom.mobicash",      # LinkAja
    "com.bca",                  # BCA Mobile / myBCA
    "id.co.bri.brimo",          # BRImo
    "id.bmri.livin",            # Livin by Mandiri
    "id.bni.mobilebanking"      # BNI Mobile
]

class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"webhook_url": DEFAULT_VPS_URL, "secret": ""}

def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

def load_seen_keys() -> set:
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                data = json.load(f)
                return set(data[-1000:])  # simpan 1000 notifikasi terakhir
        except Exception:
            pass
    return set()

def save_seen_keys(seen: set):
    try:
        with open(SEEN_FILE, "w") as f:
            json.dump(list(seen)[-1000:], f)
    except Exception:
        pass

def check_termux_api() -> bool:
    """Memeriksa apakah command termux-notification-list tersedia"""
    try:
        res = subprocess.run(["which", "termux-notification-list"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0
    except Exception:
        return False

def get_notifications() -> list:
    """Mengambil daftar notifikasi aktif di Android tray"""
    try:
        proc = subprocess.run(
            ["termux-notification-list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout.strip())
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        # Jika error JSON atau termux-api belum diizinkan
        pass
    return []

def forward_to_vps(webhook_url: str, secret: str, package: str, title: str, body: str) -> bool:
    """Mengirim payload notifikasi ke VPS SATSET-PAY"""
    payload = {
        "package": package,
        "title": title,
        "body": body,
        "secret": secret
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SATSET-Termux-Listener/1.0"
    }
    if secret:
        headers["X-Webhook-Secret"] = secret

    try:
        if HAS_REQUESTS:
            resp = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
            return resp.status_code in [200, 201]
        else:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(webhook_url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status in [200, 201]
    except Exception as e:
        print(f" {Colors.RED}[!] Gagal kirim ke VPS: {e}{Colors.RESET}")
        return False

def create_notif_hash(item: dict) -> str:
    """Membuat hash unik dari notifikasi untuk mencegah duplikasi"""
    key = f"{item.get('packageName', '')}:{item.get('title', '')}:{item.get('content', '')}:{item.get('when', '')}:{item.get('id', '')}"
    return hashlib.md5(key.encode("utf-8")).hexdigest()

def is_payment_notification(item: dict) -> bool:
    """Filter cerdas apakah notifikasi ini berkaitan dengan transaksi pembayaran"""
    pkg = (item.get("packageName") or "").lower()
    title = (item.get("title") or "").lower()
    content = (item.get("content") or item.get("bigText") or "").lower()
    combined = f"{title} {content}"

    # Cek package name target
    for tp in TARGET_PACKAGES:
        if tp in pkg:
            return True

    # Cek kata kunci pembayaran
    for kw in TARGET_KEYWORDS:
        if kw in combined:
            return True

    return False

def print_banner(webhook_url: str):
    os.system("clear")
    print(f"{Colors.CYAN}{Colors.BOLD}")
    print("┌────────────────────────────────────────────────────────────┐")
    print("│   ⚡ SATSET-PAY: TERMUX NOTIFICATION LISTENER DAEMON ⚡    │")
    print("│       100% Bebas Iklan • Ringan • Real-Time Forwarder      │")
    print("└────────────────────────────────────────────────────────────┘")
    print(f"{Colors.RESET}")
    print(f" • Status Server VPS : {Colors.GREEN}{webhook_url}{Colors.RESET}")
    print(f" • Interval Pindai   : {Colors.YELLOW}2 Detik{Colors.RESET}")
    print(f" • Mode Latar Belakang: {Colors.GREEN}Aktif (Termux Wake-Lock){Colors.RESET}")
    print(f" • Tekan {Colors.BOLD}Ctrl + C{Colors.RESET} untuk menghentikan.")
    print("─" * 60)
    print(f"{Colors.BOLD}MENUNGGU NOTIFIKASI DANA MASUK (GoBiz / Shopee / DANA)...{Colors.RESET}\n")

def main():
    cfg = load_config()

    # Argumen CLI opsional
    if len(sys.argv) > 1:
        if sys.argv[1] in ["--help", "-h"]:
            print(f"{Colors.CYAN}SATSET-PAY Termux Notification Listener{Colors.RESET}")
            print("Penggunaan:")
            print("  satset         : Jalankan listener pemantau notifikasi")
            print("  satset --test  : Kirim notifikasi simulasi ke VPS untuk tes koneksi")
            print("  satset --setup : Ubah alamat Webhook URL VPS atau Secret")
            print("  satset --help  : Tampilkan pesan bantuan ini")
            return
        elif sys.argv[1] == "--setup":
            print(f"{Colors.CYAN}--- Konfigurasi SATSET-PAY Termux ---{Colors.RESET}")
            new_url = input(f"Masukkan Webhook URL [{cfg.get('webhook_url', DEFAULT_VPS_URL)}]: ").strip()
            if new_url:
                cfg["webhook_url"] = new_url
            new_sec = input(f"Masukkan Webhook Secret (kosongkan jika tidak ada): ").strip()
            cfg["secret"] = new_sec
            save_config(cfg)
            print(f"{Colors.GREEN}Konfigurasi disimpan! Jalankan ulang tanpa argumen.{Colors.RESET}")
            return
        elif sys.argv[1] == "--test":
            print(f"{Colors.YELLOW}Mengirim tes notifikasi palsu ke VPS...{Colors.RESET}")
            ok = forward_to_vps(
                cfg.get("webhook_url", DEFAULT_VPS_URL),
                cfg.get("secret", ""),
                package="com.gojek.merchant",
                title="Penerimaan GoPay",
                body="Penerimaan GoPay: Rp 1.156 berhasil diterima dari Uji Coba Termux"
            )
            if ok:
                print(f"{Colors.GREEN}[✓] Sukses terkirim dan diterima VPS!{Colors.RESET}")
            else:
                print(f"{Colors.RED}[✗] Gagal terhubung ke VPS. Cek port 8088 atau URL.{Colors.RESET}")
            return

    # Periksa termux-api
    if not check_termux_api():
        print(f"{Colors.RED}[FATAL] Paket termux-api tidak ditemukan!{Colors.RESET}")
        print("Silakan jalankan di Termux:")
        print(f"  {Colors.YELLOW}pkg update && pkg install termux-api python -y{Colors.RESET}")
        print("Dan pastikan aplikasi 'Termux:API' sudah terpasang dari F-Droid serta diberikan izin Akses Notifikasi.")
        sys.exit(1)

    # Aktifkan wake-lock agar Termux tidak mati saat layar HP mati
    try:
        subprocess.run(["termux-wake-lock"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        pass

    seen_keys = load_seen_keys()
    webhook_url = cfg.get("webhook_url", DEFAULT_VPS_URL)
    secret = cfg.get("secret", "")

    # Inisialisasi awal: Tandai semua notifikasi lama yang sudah ada saat ini agar tidak terkirim ulang
    initial_notifs = get_notifications()
    for item in initial_notifs:
        seen_keys.add(create_notif_hash(item))
    save_seen_keys(seen_keys)

    print_banner(webhook_url)

    total_forwarded = 0

    try:
        while True:
            notifs = get_notifications()
            for item in notifs:
                h = create_notif_hash(item)
                if h in seen_keys:
                    continue

                seen_keys.add(h)
                save_seen_keys(seen_keys)

                if is_payment_notification(item):
                    pkg = item.get("packageName", "unknown")
                    title = item.get("title", "")
                    content = item.get("content") or item.get("bigText") or ""
                    now_str = datetime.now().strftime("%H:%M:%S")

                    print(f"[{now_str}] {Colors.CYAN}Ditemukan Notifikasi:{Colors.RESET} {title}")
                    print(f"          {Colors.BOLD}Isi:{Colors.RESET} {content}")
                    print(f"          {Colors.YELLOW}Mengirim ke VPS...{Colors.RESET}", end="", flush=True)

                    success = forward_to_vps(webhook_url, secret, pkg, title, content)
                    if success:
                        total_forwarded += 1
                        print(f"\r[{now_str}] {Colors.GREEN}✓ BERHASIL DITERUSKAN KE VPS! Total: {total_forwarded} transaksi.{Colors.RESET}")
                    else:
                        print(f"\r[{now_str}] {Colors.RED}✗ GAGAL DITERUSKAN (Cek koneksi internet/VPS).{Colors.RESET}")
                    print("─" * 60)

            time.sleep(2)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Termux Listener dihentikan oleh pengguna.{Colors.RESET}")

if __name__ == "__main__":
    main()

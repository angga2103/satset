# ⚡ SATSET - Automated Xray Multi-Protocol VPN Tunneling Stack

Skrip otomatisasi instalasi dan manajemen layanan tunneling Xray-core multi-protokol berkinerja tinggi untuk server VPS Debian dan Ubuntu. Dilengkapi dengan manajemen limit kuota, deteksi multi-login auto-lock, bot Telegram, integrasi Nginx reverse proxy, dan panel kontrol berbasis teks (CLI).

---

## 🚀 One-Line Installer (Instalasi Cepat)

Jalankan perintah satu baris berikut di terminal VPS Anda sebagai **root**:

```bash
apt update -y && apt install -y curl wget screen && screen -S setup-session bash -c "wget -q https://raw.githubusercontent.com/angga2103/satset/main/setup.sh && chmod +x setup.sh && ./setup.sh"
```

> [!TIP]
> **Mengapa menggunakan `screen`?**
> Jika koneksi internet atau SSH Anda terputus di tengah proses instalasi, proses di VPS tetap berjalan aman di latar belakang. Anda dapat kembali ke layar instalasi kapan saja dengan mengetik:
> ```bash
> screen -r setup-session
> ```

---

## 🛠️ Langkah-Langkah Instalasi Mandiri (Opsional)

Jika Anda ingin menjalankan instalasi langkah demi langkah:

### 1. Persiapan Sistem
Pastikan sistem mutakhir dan paket dasar tersedia:
```bash
export DEBIAN_FRONTEND=noninteractive
apt update -y && apt dist-upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
apt install -y curl wget screen sudo jq bzip2
```

### 2. Download dan Jalankan Setup
```bash
wget -q https://raw.githubusercontent.com/angga2103/satset/main/setup.sh
chmod +x setup.sh
./setup.sh
```

### 3. Ikuti Panduan Interaktif
- Tekan **Enter** untuk memulai pemeriksaan sistem.
- Masukkan nama domain/subdomain Anda yang sudah di-*pointing* (A record) ke IP VPS.
- Tunggu hingga proses instalasi seluruh komponen selesai.
- Tekan **Enter** saat instalasi selesai untuk me-*reboot* VPS.

---

## 🌐 Protokol & Port yang Didukung

| Protokol | Transport | Port TLS / HTTPS | Port Non-TLS / HTTP |
| :--- | :--- | :--- | :--- |
| **VMess** | WebSocket (WS) & gRPC | 443, 444, 8443, 2053, 2083, 2087, 2096 | 80, 8080, 8880, 2052, 2082, 2086, 2095 |
| **VLess** | WebSocket (WS) & gRPC | 443, 444, 8443, 2053, 2083, 2087, 2096 | 80, 8080, 8880, 2052, 2082, 2086, 2095 |
| **Trojan** | WebSocket (WS) & gRPC | 443, 444, 8443, 2053, 2083, 2087, 2096 | - |
| **Shadowsocks** | WebSocket (WS) & gRPC | 443, 444, 8443, 2053, 2083, 2087, 2096 | 80, 8080, 8880, 2052, 2082, 2086, 2095 |
| **Web Server** | Nginx Direct (Web Page) | 81 (SSL) | - |

---

## 🖥️ Matriks Dukungan Sistem Operasi

| Sistem Operasi | Rilis / Versi | Status Kompatibilitas |
| :--- | :--- | :--- |
| **Debian** | 10 (Buster) | ✅ Didukung (Stable) |
| **Debian** | 11 (Bullseye) | ✅ Didukung (Stable) |
| **Debian** | 12 (Bookworm) | ✅ Didukung Penuh (Tested) |
| **Ubuntu** | 20.04 LTS (Focal Fossa) | ✅ Didukung (Stable) |
| **Ubuntu** | 22.04 LTS (Jammy Jellyfish) | ✅ Didukung Penuh (Tested) |
| **Ubuntu** | 24.04 LTS (Noble Numbat) | ✅ Didukung Penuh (Tested) |

> [!NOTE]
> **Spesifikasi Minimal VPS:**
> - Arsitektur: `x86_64` (AMD64)
> - RAM: Minimal 1 GB (Dilengkapi auto-swap 2GB untuk stabilitas)
> - Disk: Minimal 10 GB SSD
> - CPU: 1 Core

---

## ✨ Fitur Utama

- **Core Modern**: Menggunakan Xray-core v25.x dengan dukungan protokol TLS 1.3, multiplexing, dan gRPC stream.
- **Nginx Reverse Proxy Terpadu**: Pemisahan jalur path WebSocket (`/vmess`, `/vless`, `/trojan-ws`, `/ss-ws`) dan gRPC service name yang aman dan teruji.
- **Auto SSL & Fallback Resilient**: Ditenagai oleh `acme.sh` resmi dengan penyedia Let's Encrypt, serta *self-signed fallback* darurat agar layanan web dan proxy tidak pernah *crash* saat DNS domain masih masa propagasi.
- **Pembatasan Kuota & IP Real-time**: Service otomatis per menit untuk memantau pemakaian kuota dan mengunci akun pengguna yang melebihi batas login (*anti multi-login*).
- **Notifikasi Bot Telegram**: Notifikasi instan ke grup/channel admin ketika ada pengguna yang terkunci, masa aktif habis, atau limit kuota tercapai.
- **Pengoptimalan Jaringan BBR & TCP**: Sysctl kernel tuning teroptimasi untuk latensi rendah (*low latency*) dan *throughput* tinggi.
- **CLI Dashboard Cepat**: Cukup ketik `menu` di terminal untuk mengakses semua fitur manajemen akun dan server.

---

## 📋 Perintah Cepat (Shortcuts)

Ketik perintah berikut langsung di terminal VPS Anda:

- `menu` : Membuka Menu Utama VPS
- `m-vmess` : Kelola Akun VMess (Buat Akun, Trial, Cek Login, Perpanjang, Hapus)
- `m-vless` : Kelola Akun VLess
- `m-trojan` : Kelola Akun Trojan
- `m-shadowsocks` : Kelola Akun Shadowsocks
- `m-bot` : Pengaturan Bot Telegram Notifikasi & Panel
- `m-domain` : Ganti Domain atau Perbarui Sertifikat SSL
- `fixcert` : Memperbarui / Menerbitkan Ulang Sertifikat SSL Domain
- `speedtest` : Menjalankan Pengujian Kecepatan Jaringan VPS
- `running` / `restart` : Memeriksa Status & Memulai Ulang Semua Layanan

---

## 🔧 Pemecahan Masalah (Troubleshooting)

### 1. Sertifikat SSL Gagal Terbit
Pastikan domain sudah terarah ke IP VPS dengan mengetik:
```bash
ping namadomain.com
```
Jika IP sudah sesuai namun SSL belum aktif, perbarui sertifikat dengan:
```bash
fixcert
```

### 2. Memeriksa Status Layanan
```bash
systemctl status xray
systemctl status nginx
systemctl status fail2ban
```

### 3. Menjalankan Update Skrip Terbaru
```bash
wget -q https://raw.githubusercontent.com/angga2103/satset/main/update.sh && chmod +x update.sh && ./update.sh
```

### 4. Mirror Repositori Bermasalah (misal: `cermin.rumahweb.id`)
Skrip instalasi sudah secara otomatis mendeteksi dan mengalihkan mirror bermasalah seperti `cermin.rumahweb.id` ke server mirror resmi Ubuntu/Debian. Jika Anda mengalami kegagalan saat menjalankan `apt update` manual sebelum instalasi, jalankan perintah ini:
- **Untuk Ubuntu:**
  ```bash
  sudo sed -i 's/cermin.rumahweb.id/archive.ubuntu.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
  ```
- **Untuk Debian:**
  ```bash
  sudo sed -i 's/cermin.rumahweb.id/deb.debian.org/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
  ```
Lalu ulangi `apt update -y`.

---

## 📄 Lisensi
Skrip ini dilisensikan di bawah lisensi terbuka [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

# 📱 Panduan Listener Notifikasi Android via Termux (100% Bebas Iklan)

Solusi alternatif resmi pengganti MacroDroid yang jauh lebih stabil, **100% bebas iklan**, sangat ringan (RAM < 15 MB), dan berjalan otomatis di latar belakang HP menggunakan **Termux + Termux:API**.

---

## 🌟 Mengapa Menggunakan Termux?
1. **Tanpa Iklan Sama Sekali**: Bebas iklan selamanya.
2. **Tidak Pernah Mati di Latar Belakang**: Dilengkapi fitur `termux-wake-lock` sehingga tetap memantau mutasi meskipun layar HP mati atau terkunci.
3. **Pemasangan 1-Klik**: Cukup *copy-paste* satu baris perintah di Termux, skrip langsung terpasang dan siap jalan.
4. **Ringan & Hemat Baterai**: Menggunakan daemon Python native dengan jeda polling 2 detik (< 0.1% pemakaian baterai).

---

## 🛠️ Langkah Pemasangan di HP Android (Hanya Sekali)

### Langkah 1: Pasang Aplikasi Termux & Termux:API
Pastikan Anda mengunduh versi resmi dari **F-Droid** (jangan dari Google Play Store karena Play Store versinya sudah usang/deprecated):
1. Unduh & install **Termux**: [Download via F-Droid](https://f-droid.org/packages/com.termux/)
2. Unduh & install **Termux:API**: [Download via F-Droid](https://f-droid.org/packages/com.termux.api/)

---

### Langkah 2: Berikan Izin Akses Notifikasi di HP
Agar Termux bisa membaca notifikasi dari GoBiz / ShopeePay / DANA:
1. Buka **Pengaturan HP** Anda.
2. Masuk ke menu **Aplikasi** ➔ **Akses Khusus** (atau cari kata kunci *"Akses Notifikasi"* di kolom pencarian pengaturan HP).
3. Cari **Termux:API** ➔ Aktifkan tombol **Izinkan**.

---

### Langkah 3: Jalankan Perintah Instalasi Otomatis
Buka aplikasi **Termux** di HP Anda, lalu salin dan tempel perintah satu baris berikut:

```bash
curl -fsSL https://raw.githubusercontent.com/angga2103/satset/main/satset-pay/termux_setup.sh | bash
```

Skrip ini akan otomatis:
* Memasang `python`, `termux-api`, dan dependensi sistem.
* Mengunduh mesin pemantau `termux_listener.py`.
* Membuat perintah pintasan **`satset`** di HP Anda.

---

## 🚀 Cara Menjalankan Kapan Saja

Setelah instalasi selesai, setiap kali Anda ingin menjalankan listener, cukup buka Termux dan ketik:

```bash
satset
```

Layar Termux akan menampilkan status:
```text
┌────────────────────────────────────────────────────────────┐
│   ⚡ SATSET-PAY: TERMUX NOTIFICATION LISTENER DAEMON ⚡    │
│       100% Bebas Iklan • Ringan • Real-Time Forwarder      │
└────────────────────────────────────────────────────────────┘
 • Status Server VPS : http://103.247.10.111:8088/api/v1/webhook/listener
 • Interval Pindai   : 2 Detik
 • Mode Latar Belakang: Aktif (Termux Wake-Lock)
 • Tekan Ctrl + C untuk menghentikan.
────────────────────────────────────────────────────────────
MENUNGGU NOTIFIKASI DANA MASUK (GoBiz / Shopee / DANA)...
```

---

## 🧪 Uji Coba Koneksi ke VPS
Untuk menguji apakah HP Anda sudah berhasil terhubung dan mengirimkan data ke VPS, ketik:
```bash
satset --test
```
Jika berhasil, terminal Termux akan menampilkan:
`[✓] Sukses terkirim dan diterima VPS!`

---

## ⚙️ Perintah Tambahan
* `satset --setup` : Mengubah alamat IP / Domain VPS jika Anda berganti VPS.
* `satset --help`  : Melihat opsi perintah yang tersedia.

# ⚡ SATSET-PAY - Self-Hosted Micro QRIS Payment Gateway

**SATSET-PAY** adalah modul Payment Gateway QRIS mandiri (*Self-Hosted*) berkinerja tinggi, ringan, dan mandiri (*standalone*). Didesain khusus untuk komunitas pengembang, pemilik Bot Telegram Store, panel PPOB, top-up voucher, dan toko digital untuk menerima pembayaran QRIS otomatis tanpa potongan fee pihak ketiga dan uang langsung masuk ke e-wallet/rekening pribadi saat itu juga.

---

## 🌟 Fitur Utama

- **100% Bebas Biaya Fee Platform**: Uang pembayaran masuk langsung detik itu juga ke akun **GoPay (GoBiz)**, **ShopeePay (Shopee Partner)**, atau **DANA Bisnis** Anda.
- **Auto-Confirm Real-Time**: Sinkronisasi instan via push notification listener dari smartphone Android tanpa jeda settlement (langsung lunas).
- **EMVCo Dynamic QRIS Engine**: Mengubah string QRIS statis menjadi QRIS dinamis berstandar nasional (ASPI/BI) lengkap dengan checksum **CRC-16/CCITT-FALSE**. Nominal transfer otomatis terkunci di aplikasi perbankan pembeli tanpa perlu diketik manual!
- **Sistem Kode Unik Pintar**: Mencegah tabrakan nominal saat ada banyak transaksi bersamaan (misal `Rp 10.147`, `Rp 10.258`).
- **Halaman Checkout Web Modern (`/pay/<invoice_no>`)**: Desain mobile-first elegan, responsif, dilengkapi timer countdown dan *auto-status polling* (halaman otomatis berubah sukses saat pembeli selesai transfer).
- **Web Dashboard Admin**: Panel manajemen API Key merchant, log mutasi masuk, statistik grafik omset harian & bulanan, simulator webhook, dan pengaturan QRIS.
- **Multi-Merchant & API Keys**: Bisa digunakan sendiri atau disewakan ke teman/kalangan sendiri dengan API Key dan webhook callback terpisah untuk masing-masing client.
- **REST API Standar Developer**: Sangat mudah diintegrasikan dengan Bot Telegram, website toko online, script Python, PHP, Node.js, dll.

---

## 🏗️ Cara Kerja Sistem

```
[Pembeli] -- Scan QRIS Dinamis (Rp 10.147)
    │
    ▼
[GoPay / Shopee / DANA Server]
    │  (Kirim Push Notifikasi ke HP)
    ▼
[HP Android Listener (MacroDroid)] ── POST Webhook ──► [VPS SATSET-PAY :8088]
                                                              │
                                                     (Cocokkan Rp 10.147)
                                                              ▼
                                                    [Status LUNAS (COMPLETED)]
                                                              │
                                                              ▼
                                                    [Webhook Callback ke Client/Bot]
```

---

## 🚀 Panduan Instalasi Cepat

Jalankan perintah berikut di terminal VPS Anda sebagai **root**:

```bash
cd /root
git clone https://github.com/angga2103/satset.git
cd satset/satset-pay
chmod +x install.sh
./install.sh
```

Setelah instalasi selesai, akses Dashboard Admin di browser Anda:
- **URL Dashboard**: `http://IP_VPS:8088/admin`
- **Username Default**: `admin`
- **Password Default**: `admin123`

---

## 🔑 Dokumentasi REST API untuk Developer

Gunakan header berikut pada setiap pemanggilan API:
- `X-API-Key: <api_key_merchant>`
- `Content-Type: application/json`

### 1. Membuat Invoice Baru (`POST /api/v1/order/create`)

**Request:**
```bash
curl -X POST http://IP_VPS:8088/api/v1/order/create \
  -H "X-API-Key: sp_live_xxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "order_id": "ORDER-9912",
    "amount": 10000,
    "customer_name": "Ahmad Dani",
    "callback_url": "https://tokovpn.com/webhook"
  }'
```

**Response (201 Created):**
```json
{
  "status": "success",
  "invoice_no": "INV-20260927-A1B2",
  "order_id": "ORDER-9912",
  "amount_original": 10000,
  "unique_code": 147,
  "amount_total": 10147,
  "checkout_url": "http://IP_VPS:8088/pay/INV-20260927-A1B2",
  "qris_string": "00020101021226600016ID.CO.GOPAY.WWW...",
  "created_at": "2026-09-27 16:30:00",
  "expired_at": "2026-09-27 16:40:00"
}
```

---

### 2. Mengecek Status Pesanan (`GET /api/v1/order/<order_id>`)

**Request:**
```bash
curl -X GET http://IP_VPS:8088/api/v1/order/ORDER-9912 \
  -H "X-API-Key: sp_live_xxxx"
```

**Response (200 OK):**
```json
{
  "status": "success",
  "order": {
    "invoice_no": "INV-20260927-A1B2",
    "order_id": "ORDER-9912",
    "amount_original": 10000,
    "unique_code": 147,
    "amount_total": 10147,
    "payment_status": "completed",
    "created_at": "2026-09-27 16:30:00",
    "expired_at": "2026-09-27 16:40:00",
    "paid_at": "2026-09-27 16:32:15"
  }
}
```

---

### 3. Webhook Callback ke Client (Saat Lunas)

Ketika pembeli selesai mentransfer dan mutasi terverifikasi, SATSET-PAY akan mengirimkan HTTP POST otomatis ke `callback_url` merchant:

```json
{
  "event": "payment.completed",
  "invoice_no": "INV-20260927-A1B2",
  "order_id": "ORDER-9912",
  "amount_original": 10000,
  "amount_total": 10147,
  "status": "completed",
  "paid_at": "2026-09-27 16:32:15",
  "timestamp": 1790505135
}
```
Header menyertakan signature HMAC SHA-256: `X-Callback-Signature: <hex_digest>` menggunakan `secret_key` merchant untuk menjamin keaslian data.

---

## 📱 Panduan Setting HP Android Listener

Lihat panduan lengkap konfigurasi aplikasi **MacroDroid** di [macrodroid_guide.md](macrodroid_guide.md).

---

## 📄 Lisensi
SATSET-PAY dilisensikan di bawah lisensi terbuka [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

# 📱 Panduan Konfigurasi HP Android Listener (MacroDroid)

Panduan ini menjelaskan cara menghubungkan notifikasi dana masuk dari **GoBiz (GoPay)**, **Shopee Partner (ShopeePay)**, dan **DANA Bisnis** di smartphone Android ke server **SATSET-PAY** menggunakan aplikasi gratis **MacroDroid**.

---

## 1. Persiapan Awal

1. Siapkan 1 smartphone Android (bisa HP cadangan) yang terpasang kartu SIM / terhubung Wi-Fi 24 jam.
2. Pastikan salah satu atau ketiga aplikasi merchant berikut telah terpasang dan login:
   - **GoBiz** (Merchant GoPay)
   - **Shopee Partner** (Merchant ShopeePay)
   - **DANA / DANA Bisnis**
3. Pastikan izin push notifikasi untuk aplikasi merchant tersebut aktif dan dapat berdering / muncul di bilah notifikasi.
4. Download dan install aplikasi **MacroDroid - Device Automation** dari Google Play Store.
5. Berikan izin **Akses Notifikasi (Notification Access)** dan matikan **Penghemat Baterai (Battery Optimization)** untuk MacroDroid agar aplikasi tidak dimatikan oleh sistem Android saat layar mati.

---

## 2. Langkah Pembuatan Makro di MacroDroid

Buka aplikasi **MacroDroid** ➔ Klik **Add Macro (+)**:

### A. Bagian Trigger (Pemicu)
1. Klik tanda **(+)** pada kotak merah **Triggers**.
2. Pilih menu **Device Events** ➔ **Notification** ➔ **Notification Received**.
3. Pilih **Select Applications** ➔ Centang aplikasi:
   - `GoBiz`
   - `Shopee Partner`
   - `DANA`
4. Pada pilihan *Notification content to match*, pilih **Any content**.
5. Klik **OK**.

---

### B. Bagian Action (Tindakan)
1. Klik tanda **(+)** pada kotak biru **Actions**.
2. Pilih menu **Connectivity** ➔ **HTTP Request**.
3. Atur detail HTTP Request sebagai berikut:
   - **Request Method**: `POST`
   - **URL**: `http://IP_VPS_ANDA:8088/api/v1/webhook/listener`  
     *(Ganti `IP_VPS_ANDA` dengan alamat IP server VPS Anda atau subdomain misal `https://pay.domainanda.com/api/v1/webhook/listener`)*
   - **Content-Type**: `application/json`
   - **Custom Headers**:  
     Klik Tambah Header:
     - Nama Header: `X-Webhook-Secret`
     - Nilai: *(Masukkan Webhook Secret Anda dari menu Pengaturan di Dashboard SATSET-PAY)*
   - **Body (Text/JSON)**: Masukkan JSON berikut persis:
     ```json
     {
       "package": "[package_name]",
       "title": "[notif_title]",
       "body": "[notif_body]"
     }
     ```
     > [!TIP]
     > Teks `[package_name]`, `[notif_title]`, dan `[notif_body]` adalah variabel bawaan MacroDroid (*Magic Text*) yang otomatis membaca judul dan isi pesan notifikasi saat ada uang masuk.
4. Klik **Centang / Simpan**.

---

### C. Simpan & Aktifkan
1. Beri nama makro, misalnya: **`SATSET-PAY Forwarder`**.
2. Klik ikon centang / save di pojok kanan bawah.
3. Pastikan saklar makro dalam posisi **ON (Aktif)**.

---

## 3. Cara Menguji (Testing)

1. Buka dashboard web SATSET-PAY di browser: `http://IP_VPS:8088/admin`.
2. Masuk ke tab **🧪 Simulator Webhook** atau lakukan transaksi uji coba transfer Rp 1.000 ke QRIS GoPay/Shopee/DANA Anda.
3. Begitu notifikasi muncul di HP Anda, buka tab **Log Mutasi Masuk** di dashboard SATSET-PAY.
4. Anda akan melihat log notifikasi masuk, nominal yang diekstrak, dan status invoice otomatis berubah menjadi **LUNAS (COMPLETED)**!

---

## 4. Troubleshooting HP Listener

- **Notifikasi Tidak Terkirim ke VPS**:
  - Pastikan port `8088` di firewall VPS terbuka (`ufw allow 8088/tcp` atau buka port di Security Group Cloud Provider).
  - Tes buka URL `http://IP_VPS:8088` di browser HP untuk memastikan HP bisa mengakses VPS.
- **HP Masuk Mode Tidur (Sleep) Saat Layar Mati**:
  - Di pengaturan Android HP Anda: cari menu *Battery Optimization* ➔ Cari *MacroDroid* ➔ Pilih *Don't optimize* (Jangan batasi latar belakang).
  - Pastikan fitur *Stay Awake While Charging* di Opsi Pengembang (Developer Options) diaktifkan jika HP selalu tercolok charger.

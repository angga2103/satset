#!/bin/bash
# =========================================================
# SATSET-PAY: One-Click Installer & Service Setup
# Installs dependencies, sets up systemd service, and starts gateway
# =========================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;93m'
CYAN='\033[1;36m'
WHITE='\033[1;97m'
NC='\033[0m'

clear
echo -e "${WHITE}┌──────────────────────────────────────────────┐${NC}"
echo -e "${WHITE}│${NC}   ${GREEN}SATSET-PAY: MICRO QRIS PAYMENT GATEWAY${NC}     ${WHITE}│${NC}"
echo -e "${WHITE}├──────────────────────────────────────────────┤${NC}"
echo -e "${WHITE}│${NC} Memasang sistem Payment Gateway Mandiri...   ${WHITE}│${NC}"
echo -e "${WHITE}└──────────────────────────────────────────────┘${NC}"
echo ""

# 1. Check Root
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[ERROR] Skrip ini harus dijalankan sebagai root!${NC}"
    exit 1
fi

# 2. Install Dependencies
echo -e "${CYAN}[1/4] Memasang dependensi sistem & Python...${NC}"
export DEBIAN_FRONTEND=noninteractive
apt update -y -qq
apt install -y -qq python3 python3-pip python3-flask python3-qrcode python3-pil curl wget ufw jq 2>/dev/null || true

pip3 install -q Flask qrcode pillow 2>/dev/null || true

# 3. Setup Directory
echo -e "${CYAN}[2/4] Menyiapkan direktori aplikasi...${NC}"
INSTALL_DIR="/etc/satset/satset-pay"
mkdir -p "$INSTALL_DIR/parsers" "$INSTALL_DIR/templates" /etc/satset 2>/dev/null

# Copy or download project files into /etc/satset/satset-pay
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/app.py" ]; then
    cp -rf "${SCRIPT_DIR}/"* "$INSTALL_DIR/" 2>/dev/null || true
else
    REPO_RAW="https://raw.githubusercontent.com/angga2103/satset/main/satset-pay"
    CACHE_BUSTER="?v=$(date +%s)"
    for f in app.py config.py database.py qris_engine.py requirements.txt macrodroid_guide.md README.md install.sh; do
        curl -fsSL -o "$INSTALL_DIR/$f" "$REPO_RAW/$f${CACHE_BUSTER}" 2>/dev/null || wget -q -O "$INSTALL_DIR/$f" "$REPO_RAW/$f${CACHE_BUSTER}" 2>/dev/null || true
    done
    for f in __init__.py gobiz.py shopee.py dana.py; do
        curl -fsSL -o "$INSTALL_DIR/parsers/$f" "$REPO_RAW/parsers/$f${CACHE_BUSTER}" 2>/dev/null || wget -q -O "$INSTALL_DIR/parsers/$f" "$REPO_RAW/parsers/$f${CACHE_BUSTER}" 2>/dev/null || true
    done
    for f in login.html dashboard.html checkout.html; do
        curl -fsSL -o "$INSTALL_DIR/templates/$f" "$REPO_RAW/templates/$f${CACHE_BUSTER}" 2>/dev/null || wget -q -O "$INSTALL_DIR/templates/$f" "$REPO_RAW/templates/$f${CACHE_BUSTER}" 2>/dev/null || true
    done
fi
chmod -R 755 "$INSTALL_DIR"

# 4. Open Port in Firewall if UFW active
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
    echo -e "${CYAN}[3/4] Membuka port 8088 di firewall...${NC}"
    ufw allow 8088/tcp >/dev/null 2>&1 || true
fi

# 5. Create Systemd Service
echo -e "${CYAN}[4/4] Mendaftarkan service satset-pay...${NC}"
SERVICE_FILE="/etc/systemd/system/satset-pay.service"
cat << 'EOF' > "$SERVICE_FILE"
[Unit]
Description=SATSET-PAY Micro QRIS Payment Gateway
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/etc/satset/satset-pay
ExecStart=/usr/bin/python3 /etc/satset/satset-pay/app.py
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1
Environment=SATSET_PAY_PORT=8088

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable satset-pay.service >/dev/null 2>&1 || true
systemctl restart satset-pay.service

# 6. Shortcut CLI satset-pay
cat << 'EOFCLI' > /usr/local/sbin/satset-pay
#!/bin/bash
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[1;36m'
NC='\033[0m'

IP_VPS=$(curl -4 -s --max-time 3 ipv4.icanhazip.com 2>/dev/null || hostname -I | awk '{print $1}')

while true; do
    clear
    echo -e "${CYAN}====================================================${NC}"
    echo -e "${GREEN}      SATSET-PAY: SELF-HOSTED QRIS GATEWAY          ${NC}"
    echo -e "${CYAN}====================================================${NC}"
    STATUS=$(systemctl is-active satset-pay 2>/dev/null || echo "inactive")
    if [ "$STATUS" = "active" ]; then
        echo -e "Status Service : ${GREEN}ACTIVE (Running on port 8088)${NC}"
    else
        echo -e "Status Service : ${RED}INACTIVE / STOPPED${NC}"
    fi
    echo -e "Dashboard Admin: ${YELLOW}http://${IP_VPS}:8088/admin${NC}"
    echo -e "Webhook HP URL : ${YELLOW}http://${IP_VPS}:8088/api/v1/webhook/listener${NC}"
    echo -e "${CYAN}====================================================${NC}"
    echo -e " [1] Start / Restart Service"
    echo -e " [2] Stop Service"
    echo -e " [3] Lihat Live Log (journalctl)"
    echo -e " [4] Lihat Transaksi Terakhir (SQLite)"
    echo -e " [5] Lihat Mutasi Masuk (SQLite)"
    echo -e " [6] Jalankan Ulang Installer"
    echo -e " [0] Keluar"
    echo -e "${CYAN}====================================================${NC}"
    read -rp "Pilih menu [0-6]: " opt
    case "$opt" in
        1)
            systemctl restart satset-pay
            echo -e "${GREEN}Service berhasil direstart!${NC}"
            sleep 1.5
            ;;
        2)
            systemctl stop satset-pay
            echo -e "${YELLOW}Service dihentikan.${NC}"
            sleep 1.5
            ;;
        3)
            journalctl -u satset-pay -f -n 50
            ;;
        4)
            sqlite3 /etc/satset/satset-pay/satset_pay.db "SELECT id, invoice_no, order_id, amount_total, status, created_at FROM invoices ORDER BY id DESC LIMIT 10;" 2>/dev/null || echo "Belum ada database/transaksi."
            read -rp "Tekan Enter untuk kembali..."
            ;;
        5)
            sqlite3 /etc/satset/satset-pay/satset_pay.db "SELECT id, source, amount, is_matched, created_at FROM mutations ORDER BY id DESC LIMIT 10;" 2>/dev/null || echo "Belum ada mutasi."
            read -rp "Tekan Enter untuk kembali..."
            ;;
        6)
            bash /etc/satset/satset-pay/install.sh
            read -rp "Tekan Enter untuk kembali..."
            ;;
        0)
            exit 0
            ;;
        *)
            echo -e "${RED}Pilihan tidak valid.${NC}"
            sleep 1
            ;;
    esac
done
EOFCLI
chmod +x /usr/local/sbin/satset-pay 2>/dev/null || true

# Get Public IP
IP_VPS=$(curl -4 -s --max-time 3 ipv4.icanhazip.com 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}==================================================${NC}"
echo -e "${WHITE}  🎉 INSTALASI SATSET-PAY BERHASIL DIJALANKAN!   ${NC}"
echo -e "${GREEN}==================================================${NC}"
echo ""
echo -e "  🌐 Dashboard Admin : ${CYAN}http://${IP_VPS}:8088/admin${NC}"
echo -e "  👤 Username Admin  : ${YELLOW}admin${NC}"
echo -e "  🔑 Password Default: ${YELLOW}admin123${NC}"
echo ""
echo -e "  📱 Webhook HP URL  : ${CYAN}http://${IP_VPS}:8088/api/v1/webhook/listener${NC}"
echo ""
echo -e "${WHITE}Langkah Selanjutnya:${NC}"
echo -e "1. Buka link Dashboard di atas, login dengan user & password default."
echo -e "2. Masuk ke menu ${YELLOW}Pengaturan${NC} untuk memasukkan string QRIS GoPay/Shopee/DANA Anda."
echo -e "3. Ikuti panduan di ${CYAN}satset-pay/macrodroid_guide.md${NC} untuk setting HP listener."
echo -e "${GREEN}==================================================${NC}"
echo ""

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
mkdir -p "$INSTALL_DIR" /etc/satset 2>/dev/null

# Copy project files into /etc/satset/satset-pay
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp -rf "${SCRIPT_DIR}/"* "$INSTALL_DIR/" 2>/dev/null || true
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

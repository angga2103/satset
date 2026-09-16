#!/bin/bash
# =========================================================
# SATSET Telegram Store Bot & Pakasir QRIS Installer
# =========================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;36m'
NC='\033[0m'

if [ "${EUID}" -ne 0 ]; then
    echo -e "${RED}[ERROR] Skrip ini harus dijalankan sebagai root!${NC}"
    exit 1
fi

clear
echo -e "${BLUE}====================================================${NC}"
echo -e "${GREEN}   INSTALASI TELEGRAM STORE BOT & QRIS PAKASIR     ${NC}"
echo -e "${BLUE}====================================================${NC}"
echo ""

# 1. Pastikan dependensi sistem terpasang
echo -e "${YELLOW}[1/5] Memeriksa & memasang dependensi Python...${NC}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null 2>&1 || true
apt-get install -y python3 python3-pip python3-venv sqlite3 curl wget qrencode >/dev/null 2>&1

# 2. Siapkan direktori kerja
echo -e "${YELLOW}[2/5] Menyiapkan direktori /etc/satset/bot-store...${NC}"
mkdir -p /etc/satset/bot-store

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
REPO_RAW="https://raw.githubusercontent.com/angga2103/satset/main/bot-store"

BOT_FILES=(
    "config.py"
    "database.py"
    "pakasir.py"
    "xray_manager.py"
    "payg_worker.py"
    "bot.py"
    "requirements.txt"
    "satset-bot.service"
    "install_store.sh"
)

# Salin dari direktori lokal jika ada, atau unduh dari repositori
for file in "${BOT_FILES[@]}"; do
    if [ -n "$SCRIPT_DIR" ] && [ "$SCRIPT_DIR" != "/etc/satset/bot-store" ] && [ -f "${SCRIPT_DIR}/${file}" ]; then
        cp -f "${SCRIPT_DIR}/${file}" "/etc/satset/bot-store/${file}"
    elif [ ! -f "/etc/satset/bot-store/${file}" ] || [ "$SCRIPT_DIR" = "/dev/fd" ] || [ "$SCRIPT_DIR" = "/dev" ] || [ -z "$SCRIPT_DIR" ]; then
        wget -q -O "/etc/satset/bot-store/${file}" "${REPO_RAW}/${file}" 2>/dev/null || \
        curl -fsSL -o "/etc/satset/bot-store/${file}" "${REPO_RAW}/${file}" 2>/dev/null || true
    fi
done
chmod +x /etc/satset/bot-store/install_store.sh 2>/dev/null || true

# 3. Buat Python Virtual Environment (PEP 668 safe)
echo -e "${YELLOW}[3/5] Menyiapkan Virtual Environment Python...${NC}"
if [ ! -d "/etc/satset/venv" ]; then
    python3 -m venv /etc/satset/venv
fi
/etc/satset/venv/bin/pip install --upgrade pip >/dev/null 2>&1
/etc/satset/venv/bin/pip install -r /etc/satset/bot-store/requirements.txt >/dev/null 2>&1

# 4. Konfigurasi bot.env jika belum ada
ENV_FILE="/etc/satset/bot.env"
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${YELLOW}[4/5] Konfigurasi Pengaturan Bot Telegram & Pakasir:${NC}"
    echo ""
    prompt_read() {
        local msg="$1"
        local var_name="$2"
        if [ -e /dev/tty ] && [ ! -t 0 ]; then
            read -rp "$msg" "$var_name" </dev/tty
        else
            read -rp "$msg" "$var_name"
        fi
    }

    prompt_read "Masukkan BOT_TOKEN dari @BotFather: " input_token
    prompt_read "Masukkan ADMIN_ID (Telegram User ID): " input_admin
    prompt_read "Masukkan PAKASIR_PROJECT_SLUG: " input_slug
    prompt_read "Masukkan PAKASIR_API_KEY: " input_key
    prompt_read "Harga Paket Bulanan (Default: 8000): " input_monthly
    prompt_read "Harga PAYG Harian (Default: 300): " input_payg

    input_monthly=${input_monthly:-8000}
    input_payg=${input_payg:-300}

    cat > "$ENV_FILE" <<EOF
# SATSET Telegram Store Bot Configuration
BOT_TOKEN=${input_token}
ADMIN_ID=${input_admin}
PAKASIR_PROJECT_SLUG=${input_slug}
PAKASIR_API_KEY=${input_key}
PRICE_MONTHLY=${input_monthly}
PRICE_PAYG_DAILY=${input_payg}
PRICE_PAYG_10GB=1000
DEFAULT_IP_LIMIT=2
DEFAULT_QUOTA_GB=0
CURRENCY=Rp
EOF
    chmod 600 "$ENV_FILE"
else
    echo -e "${GREEN}[4/5] Konfigurasi ditemukan di $ENV_FILE (dilewati).${NC}"
fi

# 5. Pasang Systemd Service
echo -e "${YELLOW}[5/5] Mengaktifkan satset-bot.service...${NC}"
if [ -f "/etc/satset/bot-store/satset-bot.service" ]; then
    cp -f /etc/satset/bot-store/satset-bot.service /etc/systemd/system/satset-bot.service
elif [ -n "$SCRIPT_DIR" ] && [ -f "${SCRIPT_DIR}/satset-bot.service" ]; then
    cp -f "${SCRIPT_DIR}/satset-bot.service" /etc/systemd/system/satset-bot.service
else
    wget -q -O /etc/systemd/system/satset-bot.service "${REPO_RAW}/satset-bot.service" 2>/dev/null || \
    curl -fsSL -o /etc/systemd/system/satset-bot.service "${REPO_RAW}/satset-bot.service" 2>/dev/null || true
fi
systemctl daemon-reload
systemctl enable satset-bot.service >/dev/null 2>&1
systemctl restart satset-bot.service

# Buat shortcut CLI: bot-store
cat > /usr/local/sbin/bot-store <<'EOF'
#!/bin/bash
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;36m'
NC='\033[0m'

while true; do
    clear
    echo -e "${BLUE}====================================================${NC}"
    echo -e "${GREEN}        SATSET TELEGRAM STORE & PAYG MANAGER        ${NC}"
    echo -e "${BLUE}====================================================${NC}"
    STATUS=$(systemctl is-active satset-bot 2>/dev/null || echo "inactive")
    if [ "$STATUS" = "active" ]; then
        echo -e "Status Bot Service : ${GREEN}ACTIVE (Running)${NC}"
    else
        echo -e "Status Bot Service : ${RED}INACTIVE / STOPPED${NC}"
    fi
    echo -e "${BLUE}====================================================${NC}"
    echo -e " [1] Lihat Live Log Bot (journalctl)"
    echo -e " [2] Restart Bot Service"
    echo -e " [3] Edit Pengaturan Bot & Pakasir (/etc/satset/bot.env)"
    echo -e " [4] Lihat Database Transaksi & Pengguna"
    echo -e " [5] Jalankan Uji Coba Cek Pakasir"
    echo -e " [0] Keluar"
    echo -e "${BLUE}====================================================${NC}"
    read -rp "Pilih menu [0-5]: " opt
    case "$opt" in
        1)
            journalctl -u satset-bot -f -n 50
            ;;
        2)
            echo -e "${YELLOW}Merestart satset-bot.service...${NC}"
            systemctl restart satset-bot
            echo -e "${GREEN}Selesai!${NC}"
            sleep 2
            ;;
        3)
            nano /etc/satset/bot.env
            systemctl restart satset-bot
            ;;
        4)
            sqlite3 /etc/satset/store.db "SELECT user_id, username, balance FROM users LIMIT 20;"
            read -rp "Tekan Enter untuk kembali..."
            ;;
        5)
            /etc/satset/venv/bin/python -c "import sys; sys.path.append('/etc/satset/bot-store'); import pakasir; print(pakasir.check_transaction('TEST'))"
            read -rp "Tekan Enter untuk kembali..."
            ;;
        0)
            break
            ;;
        *)
            echo "Pilihan tidak valid."
            sleep 1
            ;;
    esac
done
EOF
chmod +x /usr/local/sbin/bot-store

echo ""
echo -e "${GREEN}====================================================${NC}"
echo -e "${GREEN}   INSTALASI BOT STORE SATSET BERHASIL DISELESAIKAN!${NC}"
echo -e "${GREEN}====================================================${NC}"
echo -e "• Service Name : satset-bot.service"
echo -e "• Lokasi File  : /etc/satset/bot-store"
echo -e "• Konfigurasi  : /etc/satset/bot.env"
echo -e "• Kelola CLI   : Ketik ${YELLOW}bot-store${NC} di terminal kapan saja"
echo -e "${GREEN}====================================================${NC}"

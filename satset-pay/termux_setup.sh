#!/data/data/com.termux/files/usr/bin/bash
# ===================================================================
# SATSET-PAY: Installer Otomatis HP Android Listener via Termux
# 100% Bebas Iklan • Ringan • Tanpa MacroDroid
# ===================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[1;36m'
WHITE='\033[1;97m'
NC='\033[0m'

clear
echo -e "${CYAN}┌────────────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}│${NC}    ${GREEN}⚡ SATSET-PAY: TERMUX NOTIFICATION LISTENER ⚡${NC}     ${CYAN}│${NC}"
echo -e "${CYAN}├────────────────────────────────────────────────────────┤${NC}"
echo -e "${CYAN}│${NC} Pasang listener notifikasi GoBiz / Shopee / DANA di HP  ${CYAN}│${NC}"
echo -e "${CYAN}│${NC} 100% Gratis, Bebas Iklan, Otomatis Jalan di Background ${CYAN}│${NC}"
echo -e "${CYAN}└────────────────────────────────────────────────────────┘${NC}"
echo ""

# 1. Update paket & install dependensi Termux
echo -e "${YELLOW}[1/4] Memasang paket yang dibutuhkan (python, termux-api)...${NC}"
pkg install -y python termux-api libngtcp2 openssl ca-certificates -q || true

# 2. Buat folder dan unduh termux_listener.py
echo -e "${YELLOW}[2/4] Mengunduh skrip listener terbaru dari GitHub...${NC}"
mkdir -p "$HOME/satset-pay"
REPO_RAW="https://raw.githubusercontent.com/angga2103/satset/main/satset-pay/termux_listener.py"

# Download dengan python urllib (kebal error curl/libcurl dynamic linker)
if ! python3 -c "import urllib.request; urllib.request.urlretrieve('$REPO_RAW?v=$(date +%s)', '$HOME/satset-pay/termux_listener.py')" 2>/dev/null; then
    curl -fsSL "$REPO_RAW?v=$(date +%s)" -o "$HOME/satset-pay/termux_listener.py" 2>/dev/null || \
    wget -q -O "$HOME/satset-pay/termux_listener.py" "$REPO_RAW?v=$(date +%s)" 2>/dev/null || true
fi
chmod +x "$HOME/satset-pay/termux_listener.py"

# 3. Buat shortcut cepat di Termux: cukup ketik 'satset'
echo -e "${YELLOW}[3/4] Membuat perintah pintasan 'satset' di Termux...${NC}"
mkdir -p "$PREFIX/bin"
cat << 'EOF' > "$PREFIX/bin/satset"
#!/data/data/com.termux/files/usr/bin/bash
python3 "$HOME/satset-pay/termux_listener.py" "$@"
EOF
chmod +x "$PREFIX/bin/satset"

# 4. Periksa apakah termux-api berfungsi
echo -e "${YELLOW}[4/4] Memeriksa izin Akses Notifikasi Android...${NC}"
if ! command -v termux-notification-list >/dev/null 2>&1; then
    echo -e "${RED}[!] Paket termux-api belum terpasang dengan benar.${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}========================================================${NC}"
echo -e "${WHITE}  🎉 INSTALASI TERMUX LISTENER SELESAI DENGAN SUKSES!   ${NC}"
echo -e "${GREEN}========================================================${NC}"
echo ""
echo -e " ${CYAN}PENTING - PASTIKAN DUA HAL INI DI HP ANDA:${NC}"
echo -e " 1. Pastikan aplikasi ${YELLOW}'Termux:API'${NC} sudah terpasang di HP Anda."
echo -e "    (Jika belum punya, download di F-Droid: https://f-droid.org/packages/com.termux.api/)"
echo -e " 2. Berikan ${YELLOW}Izin Akses Notifikasi${NC} untuk Termux:API:"
echo -e "    ${WHITE}Pengaturan HP ➔ Aplikasi ➔ Akses Khusus ➔ Akses Notifikasi ➔ Aktifkan 'Termux:API'${NC}"
echo ""
echo -e " ${GREEN}CARA MENJALANKAN KAPAN SAJA:${NC}"
echo -e " Cukup ketik perintah ini di Termux:"
echo -e "   ${YELLOW}satset${NC}"
echo ""
echo -e " ${CYAN}Uji coba kirim notifikasi tes ke VPS:${NC}"
echo -e "   ${YELLOW}satset --test${NC}"
echo -e "${GREEN}========================================================${NC}"
echo ""

read -rp "Apakah Anda ingin langsung menjalankan listener sekarang? [Y/n]: " run_now
if [[ "$run_now" =~ ^[Yy]$ || -z "$run_now" ]]; then
    satset
fi

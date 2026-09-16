#!/usr/bin/env bash
# =========================================================
# SATSET - BadVPN UDPGW Installer (Ports 7100, 7200, 7300)
# Low Latency & High Speed Gaming UDP Gateway
# =========================================================

set -euo pipefail

green='\033[0;32m'
yellow='\033[1;33m'
red='\033[0;31m'
cyan='\033[0;36m'
nc='\033[0m'

echo -e "${cyan}[BadVPN] Memulai instalasi & konfigurasi BadVPN UDPGW...${nc}"

INSTALL_DIR="/usr/local/bin"
BADVPN_BIN="${INSTALL_DIR}/badvpn-udpgw"
PORTS=(7100 7200 7300)

mkdir -p "$INSTALL_DIR"

check_badvpn_binary() {
    local bin="$1"
    if [ -x "$bin" ]; then
        if "$bin" --version >/dev/null 2>&1 || "$bin" --help >/dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# 1. Periksa apakah binary yang ada sudah berfungsi dengan benar
if [ -f "$BADVPN_BIN" ]; then
    if ! check_badvpn_binary "$BADVPN_BIN"; then
        echo -e "${yellow}[BadVPN] Binary lama ditemukan namun tidak valid / error. Menghapus untuk reinstall...${nc}"
        rm -f "$BADVPN_BIN" /usr/bin/badvpn-udpgw
    fi
fi

# 2. Jika belum valid, coba unduh prebuilt binary
if ! check_badvpn_binary "$BADVPN_BIN"; then
    echo -e "${yellow}[BadVPN] Mencoba unduh binary precompiled badvpn-udpgw...${nc}"
    PREBUILT_URLS=(
        "https://raw.githubusercontent.com/daybreakersx/premscript/master/badvpn-udpgw64"
        "https://raw.githubusercontent.com/inoybe/vps/main/badvpn/badvpn-udpgw"
    )

    for url in "${PREBUILT_URLS[@]}"; do
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL --connect-timeout 8 -o "$BADVPN_BIN" "$url" 2>/dev/null || true
        elif command -v wget >/dev/null 2>&1; then
            wget -q --timeout=8 -O "$BADVPN_BIN" "$url" 2>/dev/null || true
        fi

        if [ -s "$BADVPN_BIN" ]; then
            chmod +x "$BADVPN_BIN"
            if check_badvpn_binary "$BADVPN_BIN"; then
                echo -e "${green}[BadVPN] Binary precompiled valid dan berhasil dipasang.${nc}"
                break
            else
                rm -f "$BADVPN_BIN"
            fi
        fi
    done
fi

# 3. Jika prebuilt tidak cocok (contoh: Ubuntu 24.04 glibc baru), kompilasi langsung dari source resmi
if ! check_badvpn_binary "$BADVPN_BIN"; then
    echo -e "${yellow}[BadVPN] Mengompilasi badvpn-udpgw dari source resmi ambrop72...${nc}"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y >/dev/null 2>&1 || true
    apt-get install -y --no-install-recommends cmake make gcc g++ git pkg-config >/dev/null 2>&1 || true

    TMP_BUILD=$(mktemp -d)
    if git clone --depth 1 https://github.com/ambrop72/badvpn.git "$TMP_BUILD/badvpn" >/dev/null 2>&1; then
        mkdir -p "$TMP_BUILD/badvpn/build"
        cd "$TMP_BUILD/badvpn/build"
        cmake .. -DCMAKE_INSTALL_PREFIX=/usr/local -DBUILD_NOTHING_BY_DEFAULT=1 -DBUILD_UDPGW=1 >/dev/null 2>&1
        make -j"$(nproc 2>/dev/null || echo 1)" >/dev/null 2>&1
        if [ -f udpgw/badvpn-udpgw ]; then
            cp -f udpgw/badvpn-udpgw "$BADVPN_BIN"
            chmod +x "$BADVPN_BIN"
            echo -e "${green}[BadVPN] Kompilasi berhasil!${nc}"
        elif [ -f badvpn-udpgw ]; then
            cp -f badvpn-udpgw "$BADVPN_BIN"
            chmod +x "$BADVPN_BIN"
            echo -e "${green}[BadVPN] Kompilasi berhasil!${nc}"
        fi
    fi
    rm -rf "$TMP_BUILD"
fi

# 4. Verifikasi akhir binary
if check_badvpn_binary "$BADVPN_BIN"; then
    ln -sf "$BADVPN_BIN" /usr/bin/badvpn-udpgw 2>/dev/null || true
    cp -f "$BADVPN_BIN" /usr/bin/badvpn-udpgw 2>/dev/null || true
else
    echo -e "${red}[BadVPN] [ERROR] Gagal memasang badvpn-udpgw binary yang dapat dijalankan di OS ini.${nc}"
    exit 1
fi

# 5. Pasang template service systemd
echo -e "${yellow}[BadVPN] Memasang unit systemd badvpn-udpgw@.service...${nc}"
cat > /etc/systemd/system/badvpn-udpgw@.service << 'EOF'
[Unit]
Description=BadVPN UDP Gateway on Port %i (Gaming & VoIP)
Documentation=https://github.com/ambrop72/badvpn
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/badvpn-udpgw --listen-addr 127.0.0.1:%i --max-clients 500 --loglevel warning
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# 6. Aktifkan dan restart untuk setiap port
for port in "${PORTS[@]}"; do
    echo -e "${cyan}[BadVPN] Mengaktifkan service badvpn-udpgw di port ${port}...${nc}"
    systemctl unmask "badvpn-udpgw@${port}" 2>/dev/null || true
    systemctl enable "badvpn-udpgw@${port}" >/dev/null 2>&1 || true
    systemctl restart "badvpn-udpgw@${port}" >/dev/null 2>&1 || true
done

# 7. Aturan firewall iptables
if command -v iptables >/dev/null 2>&1; then
    for port in "${PORTS[@]}"; do
        iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null || iptables -A INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null || true
        iptables -C INPUT -p udp --dport "$port" -j ACCEPT 2>/dev/null || iptables -A INPUT -p udp --dport "$port" -j ACCEPT 2>/dev/null || true
    done
fi

# 8. Verifikasi status
sleep 1
all_running=1
for port in "${PORTS[@]}"; do
    if systemctl is-active --quiet "badvpn-udpgw@${port}"; then
        echo -e "  • Port ${port}: ${green}ACTIVE (Running)${nc}"
    else
        echo -e "  • Port ${port}: ${red}STOPPED (Failed to start)${nc}"
        journalctl -u "badvpn-udpgw@${port}" -n 3 --no-pager 2>/dev/null || true
        all_running=0
    fi
done

if [ "$all_running" -eq 1 ]; then
    echo -e "${green}✓ BadVPN UDPGW berhasil aktif pada port: ${PORTS[*]}${nc}"
else
    echo -e "${yellow}⚠ Beberapa port BadVPN belum aktif. Periksa log systemd di atas.${nc}"
fi

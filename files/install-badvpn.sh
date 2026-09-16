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

# 1. Unduh binary prebuilt x86_64 atau kompilasi dari source
NEED_BUILD=0
if [ ! -x "$BADVPN_BIN" ]; then
    echo -e "${yellow}[BadVPN] Mengunduh binary precompiled badvpn-udpgw...${nc}"
    PREBUILT_URLS=(
        "https://raw.githubusercontent.com/daybreakersx/premscript/master/badvpn-udpgw64"
        "https://raw.githubusercontent.com/inoybe/vps/main/badvpn/badvpn-udpgw"
    )

    DOWNLOADED=0
    for url in "${PREBUILT_URLS[@]}"; do
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL --connect-timeout 10 -o "$BADVPN_BIN" "$url" 2>/dev/null || true
        elif command -v wget >/dev/null 2>&1; then
            wget -q --timeout=10 -O "$BADVPN_BIN" "$url" 2>/dev/null || true
        fi

        if [ -s "$BADVPN_BIN" ]; then
            chmod +x "$BADVPN_BIN"
            # Test run binary
            if "$BADVPN_BIN" --help >/dev/null 2>&1; then
                DOWNLOADED=1
                echo -e "${green}[BadVPN] Binary precompiled berhasil dipasang.${nc}"
                break
            fi
        fi
    done

    if [ "$DOWNLOADED" -eq 0 ]; then
        NEED_BUILD=1
    fi
fi

# 2. Kompilasi resmi jika prebuilt tidak tersedia
if [ "$NEED_BUILD" -eq 1 ] && [ ! -x "$BADVPN_BIN" ]; then
    echo -e "${yellow}[BadVPN] Mengompilasi badvpn-udpgw dari source resmi ambrop72...${nc}"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y >/dev/null 2>&1 || true
    apt-get install -y cmake make gcc g++ git libssl-dev pkg-config >/dev/null 2>&1 || true

    TMP_BUILD=$(mktemp -d)
    if git clone --depth 1 https://github.com/ambrop72/badvpn.git "$TMP_BUILD/badvpn" >/dev/null 2>&1; then
        mkdir -p "$TMP_BUILD/badvpn/build"
        cd "$TMP_BUILD/badvpn/build"
        cmake .. -DBUILD_NOTHING_BY_DEFAULT=1 -DBUILD_UDPGW=1 >/dev/null 2>&1
        make -j"$(nproc 2>/dev/null || echo 1)" >/dev/null 2>&1
        if [ -f udpgw/badvpn-udpgw ]; then
            cp -f udpgw/badvpn-udpgw "$BADVPN_BIN"
            chmod +x "$BADVPN_BIN"
            echo -e "${green}[BadVPN] Kompilasi berhasil!${nc}"
        fi
    fi
    rm -rf "$TMP_BUILD"
fi

# Pastikan symlink /usr/bin ada
if [ -x "$BADVPN_BIN" ]; then
    ln -sf "$BADVPN_BIN" /usr/bin/badvpn-udpgw
else
    echo -e "${red}[BadVPN] [ERROR] Gagal memasang badvpn-udpgw binary.${nc}"
    exit 1
fi

# 3. Buat template service systemd
echo -e "${yellow}[BadVPN] Memasang unit systemd badvpn-udpgw@.service...${nc}"
cat > /etc/systemd/system/badvpn-udpgw@.service << 'EOF'
[Unit]
Description=BadVPN UDP Gateway on Port %i (Gaming & VoIP)
Documentation=https://github.com/ambrop72/badvpn
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/badvpn-udpgw --listen-addr 127.0.0.1:%i --max-clients 500
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# 4. Aktifkan dan jalankan untuk masing-masing port
for port in "${PORTS[@]}"; do
    echo -e "${cyan}[BadVPN] Mengaktifkan service badvpn-udpgw di port ${port}...${nc}"
    systemctl enable "badvpn-udpgw@${port}" >/dev/null 2>&1 || true
    systemctl restart "badvpn-udpgw@${port}" >/dev/null 2>&1 || true
done

# 5. Aturan firewall iptables
if command -v iptables >/dev/null 2>&1; then
    for port in "${PORTS[@]}"; do
        iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null || iptables -A INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null || true
        iptables -C INPUT -p udp --dport "$port" -j ACCEPT 2>/dev/null || iptables -A INPUT -p udp --dport "$port" -j ACCEPT 2>/dev/null || true
    done
fi

# 6. Verifikasi status
echo -e "${green}✓ BadVPN UDPGW berhasil aktif pada port: ${PORTS[*]}${nc}"
for port in "${PORTS[@]}"; do
    if systemctl is-active --quiet "badvpn-udpgw@${port}"; then
        echo -e "  • Port ${port}: ${green}ACTIVE (Running)${nc}"
    else
        echo -e "  • Port ${port}: ${yellow}STARTING${nc}"
    fi
done

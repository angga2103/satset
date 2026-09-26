#!/usr/bin/env bash
# ==========================================================
# SATSET Cloudflare WARP Manager & Xray Smart Routing
# Developed for MAS ANSOR PROJECT / SATSET VPS Automation
# ==========================================================
set -eo pipefail

WARP_PORT="40000"
CONFIG_FILE="/etc/xray/config.json"
XRAY_BIN="/usr/local/bin/xray"
[ -f /usr/bin/xray ] && XRAY_BIN="/usr/bin/xray"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m'

msg_info() { echo -e "${CYAN}• $1${NC}"; }
msg_ok()   { echo -e "${GREEN}✓ $1${NC}"; }
msg_warn() { echo -e "${YELLOW}⚠ $1${NC}"; }
msg_err()  { echo -e "${RED}✗ $1${NC}"; }

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        msg_err "Skrip ini harus dijalankan sebagai root!"
        exit 1
    fi
}

detect_warp_service() {
    if systemctl is-active --quiet warp-svc 2>/dev/null; then
        echo "warp-svc"
    elif systemctl is-active --quiet warp-go 2>/dev/null; then
        echo "warp-go"
    elif command -v warp-cli >/dev/null 2>&1; then
        echo "warp-cli"
    else
        echo "none"
    fi
}

check_port_listening() {
    if ss -tlnp 2>/dev/null | grep -q ":${WARP_PORT}\b"; then
        return 0
    elif netstat -tlnp 2>/dev/null | grep -q ":${WARP_PORT}\b"; then
        return 0
    fi
    return 1
}

get_warp_ip() {
    local ip=""
    if check_port_listening; then
        ip=$(curl -s -x "socks5h://127.0.0.1:${WARP_PORT}" --max-time 4 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null | grep "^ip=" | cut -d= -f2 || true)
    fi
    echo "$ip"
}

get_current_mode() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "NO_CONFIG"
        return
    fi
    python3 -c "
import json
try:
    with open('$CONFIG_FILE') as f:
        data = json.load(f)
    rules = data.get('routing', {}).get('rules', [])
    warp_rule = next((r for r in rules if r.get('outboundTag') == 'warp'), None)
    if not warp_rule:
        print('OFF')
    elif warp_rule.get('network') == 'tcp,udp' and not warp_rule.get('domain'):
        print('FULL')
    else:
        print('SMART')
except Exception:
    print('UNKNOWN')
" 2>/dev/null || echo "UNKNOWN"
}

install_warp_client() {
    check_root
    msg_info "Menyiapkan dependensi instalasi Cloudflare WARP..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y >/dev/null 2>&1 || true
    apt-get install -y --no-install-recommends curl gnupg lsb-release ca-certificates jq >/dev/null 2>&1 || true

    # Detect OS Codename
    local codename=""
    if command -v lsb_release >/dev/null 2>&1; then
        codename=$(lsb_release -cs 2>/dev/null || true)
    fi
    if [ -z "$codename" ] && [ -f /etc/os-release ]; then
        codename=$(grep -E "^VERSION_CODENAME=" /etc/os-release | cut -d= -f2 | tr -d '"' || true)
    fi
    [ -z "$codename" ] && codename="bookworm"

    msg_info "Memasang repository resmi Cloudflare WARP untuk $codename..."
    mkdir -p /usr/share/keyrings /etc/apt/sources.list.d
    curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --yes --dearmor --output /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg 2>/dev/null || true
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $codename main" > /etc/apt/sources.list.d/cloudflare-client.list

    apt-get update -y >/dev/null 2>&1 || true
    
    local installed=0
    if apt-get install -y cloudflare-warp >/dev/null 2>&1; then
        installed=1
    fi

    if [ "$installed" -eq 1 ]; then
        msg_ok "Paket cloudflare-warp berhasil dipasang dari repository resmi."
        systemctl enable warp-svc >/dev/null 2>&1 || true
        systemctl restart warp-svc >/dev/null 2>&1 || true
        sleep 2

        msg_info "Mengonfigurasi WARP ke SOCKS5 Proxy Mode (127.0.0.1:${WARP_PORT})..."
        # Registrasi client (kompatibel sintaks baru & lama)
        warp-cli --accept-tos registration new >/dev/null 2>&1 || warp-cli --accept-tos register >/dev/null 2>&1 || true
        # Set mode proxy
        warp-cli --accept-tos mode proxy >/dev/null 2>&1 || warp-cli --accept-tos set-mode proxy >/dev/null 2>&1 || true
        # Set port 40000
        warp-cli --accept-tos proxy port "$WARP_PORT" >/dev/null 2>&1 || warp-cli --accept-tos set-proxy-port "$WARP_PORT" >/dev/null 2>&1 || true
        # Connect
        warp-cli --accept-tos connect >/dev/null 2>&1 || true
        sleep 2
    else
        msg_warn "Paket cloudflare-warp resmi tidak tersedia untuk arsitektur ini. Memasang warp-go standalone daemon..."
        install_warp_go_fallback
    fi

    # Verifikasi apakah port 40000 aktif
    if check_port_listening; then
        local warp_ip=$(get_warp_ip)
        msg_ok "Cloudflare WARP aktif di 127.0.0.1:${WARP_PORT}!"
        [ -n "$warp_ip" ] && msg_ok "IP Egress WARP: ${WHITE}${warp_ip}${NC}"
    else
        msg_warn "WARP belum mendengarkan di port ${WARP_PORT}. Mencoba restart daemon..."
        systemctl restart warp-svc 2>/dev/null || systemctl restart warp-go 2>/dev/null || true
        sleep 2
    fi
}

install_warp_go_fallback() {
    local ARCH=$(uname -m)
    local URL=""
    case "$ARCH" in
        x86_64)  URL="https://gitlab.com/fscarmen/warp/-/raw/main/warp-go_linux_amd64" ;;
        aarch64) URL="https://gitlab.com/fscarmen/warp/-/raw/main/warp-go_linux_arm64" ;;
        *)       URL="https://gitlab.com/fscarmen/warp/-/raw/main/warp-go_linux_amd64" ;;
    esac

    mkdir -p /opt/warp-go
    curl -fsSL -o /opt/warp-go/warp-go "$URL" 2>/dev/null || wget -q -O /opt/warp-go/warp-go "$URL" 2>/dev/null || true
    chmod +x /opt/warp-go/warp-go 2>/dev/null || true

    if [ -x /opt/warp-go/warp-go ]; then
        cd /opt/warp-go
        ./warp-go --register --socks5="127.0.0.1:${WARP_PORT}" >/dev/null 2>&1 || true
        
        cat > /etc/systemd/system/warp-go.service << EOF
[Unit]
Description=Cloudflare WARP-GO SOCKS5 Proxy
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/warp-go
ExecStart=/opt/warp-go/warp-go --socks5=127.0.0.1:${WARP_PORT}
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
        systemctl daemon-reload
        systemctl enable --now warp-go >/dev/null 2>&1 || true
        msg_ok "warp-go service berhasil dipasang dan diaktifkan."
    else
        msg_err "Gagal mengunduh binary warp-go."
    fi
}

uninstall_warp() {
    check_root
    msg_info "Menghapus konfigurasi WARP dan mematikan layanan..."
    
    # Matikan routing WARP di Xray
    set_xray_mode "off" >/dev/null 2>&1 || true

    # Hentikan services
    systemctl stop warp-svc warp-go 2>/dev/null || true
    systemctl disable warp-svc warp-go 2>/dev/null || true

    # Hapus paket
    apt-get remove -y --purge cloudflare-warp >/dev/null 2>&1 || true
    rm -f /etc/apt/sources.list.d/cloudflare-client.list /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
    rm -rf /opt/warp-go /etc/systemd/system/warp-go.service /var/lib/cloudflare-warp
    systemctl daemon-reload

    msg_ok "Cloudflare WARP berhasil dihapus dan Xray dikembalikan ke Direct Outbound."
}

restart_warp() {
    check_root
    local svc=$(detect_warp_service)
    if [ "$svc" == "warp-svc" ] || [ "$svc" == "warp-cli" ]; then
        msg_info "Merestart warp-svc..."
        systemctl restart warp-svc 2>/dev/null || true
        warp-cli --accept-tos connect >/dev/null 2>&1 || true
    elif [ "$svc" == "warp-go" ]; then
        msg_info "Merestart warp-go..."
        systemctl restart warp-go 2>/dev/null || true
    else
        msg_warn "Layanan WARP tidak ditemukan. Jalankan instalasi terlebih dahulu."
        return
    fi
    sleep 2
    if check_port_listening; then
        msg_ok "Layanan WARP aktif di port 127.0.0.1:${WARP_PORT}"
    else
        msg_err "WARP gagal mendengarkan di port 127.0.0.1:${WARP_PORT}"
    fi
}

patch_xray_config() {
    local target_mode="$1"
    check_root

    if [ ! -f "$CONFIG_FILE" ]; then
        msg_err "File konfigurasi Xray tidak ditemukan di $CONFIG_FILE"
        return 1
    fi

    # Backup konfigurasi sebelum modifikasi
    cp -f "$CONFIG_FILE" "${CONFIG_FILE}.warp.bak"

    python3 - << PYEOF
import json
import sys

cfg_file = "$CONFIG_FILE"
mode = "$target_mode"
warp_port = int("$WARP_PORT")

try:
    with open(cfg_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
except Exception as e:
    print(f"ERROR: Gagal membaca JSON: {e}")
    sys.exit(1)

outbounds = data.setdefault("outbounds", [])
warp_ob = next((ob for ob in outbounds if ob.get("tag") == "warp"), None)
if not warp_ob:
    warp_ob = {
        "tag": "warp",
        "protocol": "socks",
        "settings": {
            "servers": [
                {
                    "address": "127.0.0.1",
                    "port": warp_port
                }
            ]
        }
    }
    outbounds.append(warp_ob)
else:
    # Ensure port is correct
    warp_ob["settings"] = {
        "servers": [{"address": "127.0.0.1", "port": warp_port}]
    }

routing = data.setdefault("routing", {})
rules = routing.setdefault("rules", [])

# Remove existing warp rules
rules[:] = [r for r in rules if r.get("outboundTag") != "warp"]

# Streaming & AI unlock domain list
STREAMING_DOMAINS = [
    "geosite:openai",
    "geosite:netflix",
    "geosite:disney",
    "geosite:spotify",
    "geosite:tiktok",
    "geosite:youtube",
    "domain:openai.com",
    "domain:chatgpt.com",
    "domain:oaistatic.com",
    "domain:oaiusercontent.com",
    "domain:netflix.com",
    "domain:netflix.net",
    "domain:nflximg.net",
    "domain:nflxvideo.net",
    "domain:nflxso.net",
    "domain:nflxext.com",
    "domain:disneyplus.com",
    "domain:disney.com",
    "domain:dssott.com",
    "domain:bamgrid.com",
    "domain:youtube.com",
    "domain:googlevideo.com",
    "domain:ytimg.com",
    "domain:youtu.be",
    "domain:youtubei.googleapis.com",
    "domain:yt.be",
    "domain:reddit.com",
    "domain:redd.it",
    "domain:ipinfo.io"
]

import os
custom_domains_file = "/etc/satset/warp-domains.txt"
if os.path.exists(custom_domains_file):
    try:
        with open(custom_domains_file, "r") as cf:
            for line in cf:
                line = line.strip()
                if line and not line.startswith("#"):
                    if not any(line.startswith(p) for p in ("domain:", "geosite:", "regexp:", "full:")):
                        line = f"domain:{line}"
                    if line not in STREAMING_DOMAINS:
                        STREAMING_DOMAINS.append(line)
    except Exception:
        pass

if mode == "smart":
    # Insert smart media/AI rule right before the catch-all direct rule
    smart_rule = {
        "type": "field",
        "outboundTag": "warp",
        "domain": STREAMING_DOMAINS
    }
    # Find position: insert before catch-all rule
    insert_idx = len(rules)
    for i, r in enumerate(rules):
        if r.get("outboundTag") == "direct" and r.get("network") == "tcp,udp":
            insert_idx = i
            break
    rules.insert(insert_idx, smart_rule)

elif mode == "full":
    # Route all normal client traffic through warp
    full_rule = {
        "type": "field",
        "outboundTag": "warp",
        "network": "tcp,udp"
    }
    insert_idx = len(rules)
    for i, r in enumerate(rules):
        if r.get("outboundTag") == "direct" and r.get("network") == "tcp,udp":
            insert_idx = i
            break
    rules.insert(insert_idx, full_rule)

elif mode == "off":
    # All client traffic stays direct (rules already stripped of warp)
    pass

with open(cfg_file, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

print("SUCCESS")
PYEOF

    # Verifikasi konfigurasi dengan binary xray
    local test_cmd=("$XRAY_BIN" "run" "-test" "-config" "$CONFIG_FILE")
    if ! "${test_cmd[@]}" >/dev/null 2>&1; then
        test_cmd=("$XRAY_BIN" "-test" "-config" "$CONFIG_FILE")
    fi

    if "${test_cmd[@]}" >/dev/null 2>&1; then
        rm -f "${CONFIG_FILE}.warp.bak"
        systemctl restart xray 2>/dev/null || true
        return 0
    else
        msg_err "Uji konfigurasi Xray gagal! Mengembalikan backup konfigurasi..."
        cp -f "${CONFIG_FILE}.warp.bak" "$CONFIG_FILE"
        systemctl restart xray 2>/dev/null || true
        return 1
    fi
}

set_xray_mode() {
    local mode="$1"
    check_root

    # Pastikan client WARP terpasang jika memilih mode smart atau full
    if [ "$mode" != "off" ]; then
        if ! check_port_listening; then
            msg_warn "Port SOCKS5 127.0.0.1:${WARP_PORT} belum aktif. Memulai instalasi WARP Client..."
            install_warp_client
        fi
    fi

    msg_info "Mengonfigurasi rute Xray ke mode: ${WHITE}${mode^^}${NC}..."
    if patch_xray_config "$mode"; then
        case "$mode" in
            smart)
                msg_ok "Mode SMART AKTIF: YouTube, Netflix, Disney+, ChatGPT, Reddit, TikTok diarahkan lewat Cloudflare WARP."
                msg_ok "Akses web lainnya tetap direct (ping rendah & kecepatan maksimal)."
                ;;
            full)
                msg_ok "Mode FULL WARP AKTIF: Seluruh lalu lintas keluar Xray diarahkan lewat Cloudflare WARP."
                ;;
            off)
                msg_ok "WARP dinonaktifkan: Seluruh lalu lintas Xray kembali ke Direct Outbound."
                ;;
        esac
    else
        msg_err "Gagal menerapkan konfigurasi Xray."
        return 1
    fi
}

test_unlock() {
    clear
    echo -e "${WHITE}─────────────────────────────────────────────────────${NC}"
    echo -e "${GREEN}       UJI KONEKSI WARP & STATUS UNLOCK STREAMING    ${NC}"
    echo -e "${WHITE}─────────────────────────────────────────────────────${NC}"
    echo ""

    if ! check_port_listening; then
        echo -e "• Status SOCKS5 Proxy (127.0.0.1:${WARP_PORT}) : ${RED}[ TUTUP / NON-AKTIF ]${NC}"
        echo -e "  Silakan pasang atau jalankan WARP Client terlebih dahulu."
        return
    fi

    echo -e "• Status SOCKS5 Proxy (127.0.0.1:${WARP_PORT}) : ${GREEN}[ BUKA / AKTIF ]${NC}"
    
    # 1. Cloudflare Egress IP & Warp Check
    echo -ne "• Memeriksa IP Egress Cloudflare... "
    local cf_trace=$(curl -s -x "socks5h://127.0.0.1:${WARP_PORT}" --max-time 6 https://www.cloudflare.com/cdn-cgi/trace 2>/dev/null || true)
    local cf_ip=$(echo "$cf_trace" | grep "^ip=" | cut -d= -f2 || true)
    local cf_warp=$(echo "$cf_trace" | grep "^warp=" | cut -d= -f2 || true)
    local cf_loc=$(echo "$cf_trace" | grep "^loc=" | cut -d= -f2 || true)

    if [ -n "$cf_ip" ]; then
        echo -e "${GREEN}[ OK ]${NC}"
        echo -e "  - Alamat IP WARP : ${WHITE}${cf_ip}${NC} (Lokasi: ${cf_loc:-Unknown})"
        echo -e "  - Status WARP    : ${GREEN}${cf_warp^^}${NC}"
    else
        echo -e "${RED}[ TIMEOUT / GAGAL ]${NC}"
    fi

    # 2. Uji YouTube Unlock (Bypass ISP / Datacenter Block)
    echo -ne "• Menguji Akses YouTube (Bypass Datacenter Block)... "
    local yt_code=$(curl -s -o /dev/null -w "%{http_code}" -x "socks5h://127.0.0.1:${WARP_PORT}" --max-time 8 "https://www.youtube.com" 2>/dev/null || echo "000")
    if [ "$yt_code" == "200" ] || [ "$yt_code" == "301" ] || [ "$yt_code" == "302" ]; then
        echo -e "${GREEN}[ UNLOCKED / AKSES LANCAR ] (Code: $yt_code)${NC}"
    elif [ "$yt_code" == "429" ] || [ "$yt_code" == "403" ]; then
        echo -e "${RED}[ BLOCKED / CAPTCHA ROBOT ] (Code: $yt_code)${NC}"
    else
        echo -e "${YELLOW}[ RESPON LAIN ] (Code: $yt_code)${NC}"
    fi

    # 3. Uji Netflix Unlock
    echo -ne "• Menguji Akses Netflix (Bypass Datacenter Block)... "
    local nf_code=$(curl -s -o /dev/null -w "%{http_code}" -x "socks5h://127.0.0.1:${WARP_PORT}" --max-time 8 "https://www.netflix.com/title/80018499" 2>/dev/null || echo "000")
    if [ "$nf_code" == "200" ]; then
        echo -e "${GREEN}[ UNLOCKED / RESIDENTIAL SUPPORT ] (Code: 200)${NC}"
    elif [ "$nf_code" == "403" ] || [ "$nf_code" == "404" ]; then
        echo -e "${YELLOW}[ ORIGINAL ONLY / REGION RESTRICTED ] (Code: $nf_code)${NC}"
    else
        echo -e "${RED}[ BLOCKED / TIMEOUT ] (Code: $nf_code)${NC}"
    fi

    # 4. Uji OpenAI / ChatGPT Access
    echo -ne "• Menguji Akses ChatGPT / OpenAI... "
    local ai_code=$(curl -s -o /dev/null -w "%{http_code}" -x "socks5h://127.0.0.1:${WARP_PORT}" --max-time 8 "https://chatgpt.com" 2>/dev/null || echo "000")
    if [ "$ai_code" == "200" ] || [ "$ai_code" == "307" ] || [ "$ai_code" == "302" ]; then
        echo -e "${GREEN}[ UNLOCKED / ACCESS GRANTED ] (Code: $ai_code)${NC}"
    elif [ "$ai_code" == "403" ]; then
        echo -e "${RED}[ ACCESS DENIED / CAPTCHA ] (Code: 403)${NC}"
    else
        echo -e "${YELLOW}[ RESPON LAIN ] (Code: $ai_code)${NC}"
    fi

    # 5. Mode Xray saat ini
    local current_mode=$(get_current_mode)
    echo ""
    echo -e "• Mode Routing Xray Aktif : ${CYAN}[ ${current_mode} ]${NC}"
    echo -e "${WHITE}─────────────────────────────────────────────────────${NC}"
}

show_status() {
    clear
    local svc=$(detect_warp_service)
    local port_stat="${RED}[ CLOSED ]${NC}"
    local warp_ip="-"
    local xray_mode=$(get_current_mode)

    if check_port_listening; then
        port_stat="${GREEN}[ LISTENING (127.0.0.1:${WARP_PORT}) ]${NC}"
        warp_ip=$(get_warp_ip)
        [ -z "$warp_ip" ] && warp_ip="Terhubung (IP Hidden)"
    fi

    local svc_stat="${RED}[ STOPPED ]${NC}"
    if [ "$svc" != "none" ]; then
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            svc_stat="${GREEN}[ RUNNING ($svc) ]${NC}"
        fi
    fi

    local mode_display="${YELLOW}[ DIRECT (WARP OFF) ]${NC}"
    if [ "$xray_mode" == "SMART" ]; then
        mode_display="${GREEN}[ SMART MEDIA & AI UNLOCK ]${NC}"
    elif [ "$xray_mode" == "FULL" ]; then
        mode_display="${CYAN}[ FULL WARP OUTBOUND ]${NC}"
    fi

    echo -e "${WHITE}─────────────────────────────────────────────────────${NC}"
    echo -e "${GREEN}             STATUS CLOUDFLARE WARP MANAGER          ${NC}"
    echo -e "${WHITE}─────────────────────────────────────────────────────${NC}"
    echo -e "• Service Daemon    : $svc_stat"
    echo -e "• SOCKS5 Local Port : $port_stat"
    echo -e "• Cloudflare IP     : ${WHITE}$warp_ip${NC}"
    echo -e "• Xray Routing Mode : $mode_display"
    echo -e "${WHITE}─────────────────────────────────────────────────────${NC}"
}

case "${1:-}" in
    install)
        install_warp_client
        ;;
    uninstall)
        uninstall_warp
        ;;
    restart)
        restart_warp
        ;;
    smart)
        set_xray_mode "smart"
        ;;
    full)
        set_xray_mode "full"
        ;;
    off)
        set_xray_mode "off"
        ;;
    test)
        test_unlock
        ;;
    status)
        show_status
        ;;
    *)
        show_status
        ;;
esac

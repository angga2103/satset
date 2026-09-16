#!/usr/bin/env bash
set -Eeuo pipefail

LOGFILE="/root/setup.log"
exec > >(tee -a "$LOGFILE") 2>&1

############################################
# TRAP ERROR
############################################
trap 'echo "[FATAL] Error di baris $LINENO. Cek $LOGFILE"; exit 1' ERR

############################################
# KONFIG LOCKED
############################################
XRAY_VERSION="25.5.16"
REPO_RAW="https://raw.githubusercontent.com/angga2103/satset/main"
CROWDSEC_AUTO_ENROLL="OFF"
IPTABLES_LIMIT_MODE="NORMAL"

export DEBIAN_FRONTEND=noninteractive

############################################
# UTIL
############################################
info(){ echo -e "\e[1;36m[INFO]\e[0m $*"; }
ok(){ echo -e "\e[1;32m[OK]\e[0m $*"; }
warn(){ echo -e "\e[1;33m[WARN]\e[0m $*"; }
die(){ echo -e "\e[1;31m[FATAL]\e[0m $*"; exit 1; }

############################################
# VALIDASI
############################################
[[ $EUID -eq 0 ]] || die "Jalankan sebagai root"

. /etc/os-release
[[ "${ID}" == "ubuntu" || "${ID}" == "debian" ]] || die "OS tidak didukung"
[[ "$(uname -m)" == "x86_64" ]] || die "Arsitektur tidak didukung"

############################################
# PRECHECK
############################################
info "Precheck environment"
command -v curl >/dev/null || die "curl tidak ada"
command -v wget >/dev/null || die "wget tidak ada"
ok "Precheck OK"

############################################
# PAKET DASAR
############################################
info "Install paket dasar"
if grep -rq "cermin.rumahweb.id" /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
  info "Mengganti mirror cermin.rumahweb.id ke mirror resmi"
  if grep -qi "ubuntu" /etc/os-release 2>/dev/null; then
    sed -i 's/cermin.rumahweb.id/archive.ubuntu.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
  else
    sed -i 's/cermin.rumahweb.id/deb.debian.org/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
  fi
fi
apt update -y
apt install -y \
  ca-certificates gnupg lsb-release \
  curl wget jq unzip tar xz-utils \
  net-tools iproute2 \
  nginx cron \
  iptables iptables-persistent \
  fail2ban vnstat rsyslog dropbear \
  software-properties-common
ok "Paket dasar OK"

############################################
# STRUKTUR DIREKTORI (KOMPATIBEL REPO)
############################################
info "Menyiapkan direktori"
mkdir -p /etc/xray /var/log/xray /var/www/html
mkdir -p /etc/{vmess,vless,trojan,shadowsocks,ssh,bot}
mkdir -p /etc/limit/{vmess,vless,trojan,shadowsocks,ssh}/{ip,}
mkdir -p /detail/{vmess,vless,trojan,shadowsocks,ssh}
touch /etc/ssh/.ssh.db
mkdir -p /etc/user-create /usr/local/sbin /usr/local/bin
touch /etc/xray/domain /var/log/xray/{access.log,error.log}
chown -R www-data:www-data /var/log/xray
ok "Direktori siap"

############################################
# DOMAIN
############################################
EXISTING_DOMAIN=""
if [ -s /etc/xray/domain ]; then
  EXISTING_DOMAIN=$(head -n1 /etc/xray/domain | tr -d ' \t\r\n')
elif [ -s /root/domain ]; then
  EXISTING_DOMAIN=$(head -n1 /root/domain | tr -d ' \t\r\n')
fi

if [[ "$EXISTING_DOMAIN" =~ ^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
  DOMAIN="$EXISTING_DOMAIN"
  ok "Menggunakan domain tersimpan: $DOMAIN"
else
  RECOVERED_DOMAIN=$(openssl x509 -in /etc/xray/xray.crt -noout -subject 2>/dev/null | grep -oP 'CN\s*=\s*\K[^\s,]+' | grep -v 'localhost' | head -n1 || true)
  if [[ ! "$RECOVERED_DOMAIN" =~ ^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] && [ -d /root/.acme.sh ]; then
    RECOVERED_DOMAIN=$(find /root/.acme.sh -maxdepth 1 -name "*.*" -type d 2>/dev/null | head -n1 | sed 's/.*\///; s/_ecc$//' || true)
  fi

  if [[ "$RECOVERED_DOMAIN" =~ ^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]; then
    DOMAIN="$RECOVERED_DOMAIN"
    ok "Domain dipulihkan dari sertifikat SSL: $DOMAIN"
  else
    if [ -e /dev/tty ]; then
      read -rp "Masukkan domain (FQDN): " DOMAIN < /dev/tty || true
    else
      DOMAIN="${1:-}"
    fi
    DOMAIN=$(echo "${DOMAIN:-}" | tr -d ' \t\r\n')
    [[ "$DOMAIN" =~ ^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] || die "Domain tidak valid: '$DOMAIN'"
  fi
fi
echo "$DOMAIN" > /etc/xray/domain
echo "$DOMAIN" > /root/domain
ok "Domain diset: $DOMAIN"

############################################
# SSL (ACME.SH RESMI)
############################################
info "Install SSL"
systemctl stop nginx || true
curl -fsSL https://get.acme.sh | sh || true
~/.acme.sh/acme.sh --set-default-ca --server letsencrypt || true
~/.acme.sh/acme.sh --issue -d "$DOMAIN" --standalone -k ec-256 || true
~/.acme.sh/acme.sh --installcert -d "$DOMAIN" \
  --fullchainpath /etc/xray/xray.crt \
  --keypath /etc/xray/xray.key --ecc || true
if [ ! -s /etc/xray/xray.crt ] || [ ! -s /etc/xray/xray.key ]; then
  warn "Sertifikat Let's Encrypt belum berhasil diterbitkan. Membuat self-signed cert sementara..."
  openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/xray/xray.key -out /etc/xray/xray.crt \
    -subj "/C=ID/ST=Jakarta/L=Jakarta/O=VPN/OU=Server/CN=$DOMAIN" >/dev/null 2>&1
fi
chmod 600 /etc/xray/xray.key
ok "SSL OK"

############################################
# XRAY CORE
############################################
info "Install Xray $XRAY_VERSION"
mkdir -p /run/xray
chown www-data:www-data /run/xray
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" \
  @ install -u www-data --version "$XRAY_VERSION"
wget -q -O /etc/xray/config.json "$REPO_RAW/config/config.json"
mkdir -p /usr/local/share/xray
wget -q -O /usr/local/share/xray/geosite.dat "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat" 2>/dev/null || true
wget -q -O /usr/local/share/xray/geoip.dat "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat" 2>/dev/null || true
ok "Xray OK"

############################################
# NGINX CONFIG
############################################
info "Konfigurasi Nginx"
wget -q -O /etc/nginx/conf.d/xray.conf "$REPO_RAW/config/xray.conf"
sed -i "s/xxx/$DOMAIN/g" /etc/nginx/conf.d/xray.conf
wget -q -O /etc/nginx/nginx.conf "$REPO_RAW/config/nginx.conf"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx
ok "Nginx OK"

############################################
# DROPBEAR & SSH WEBSOCKET TUNNEL
############################################
info "Setup Dropbear & SSH WebSocket Tunnel"
cat > /etc/default/dropbear <<'EOF'
NO_START=0
DROPBEAR_PORT=109
DROPBEAR_EXTRA_ARGS="-p 143"
DROPBEAR_BANNER="/etc/issue.net"
DROPBEAR_RECEIVE_WINDOW=65536
EOF
cat > /etc/issue.net <<'EOF'
<font color="blue"><b>================================</b></font><br>
<font color="green"><b>   SATSET PREMIUM TUNNELING SERVER   </b></font><br>
<font color="blue"><b>================================</b></font><br>
<font color="red"><b>TERMS OF SERVICE:</b></font><br>
<font color="white"><b>- NO DDOs / SPAM / HACKING</b></font><br>
<font color="white"><b>- NO TORRENT / P2P</b></font><br>
<font color="white"><b>- MAX 2 DEVICES / MULTILOGIN</b></font><br>
<font color="blue"><b>================================</b></font>
EOF
systemctl enable dropbear >/dev/null 2>&1 || true
systemctl restart dropbear >/dev/null 2>&1 || true

wget -q -O /usr/local/bin/ws-stunnel "$REPO_RAW/files/ws-stunnel.py" || true
chmod +x /usr/local/bin/ws-stunnel 2>/dev/null || true
wget -q -O /etc/systemd/system/ws-stunnel.service "$REPO_RAW/files/ws-stunnel.service" || true
systemctl daemon-reload >/dev/null 2>&1 || true
systemctl enable --now ws-stunnel >/dev/null 2>&1 || true
ok "Dropbear & SSH WS Tunnel OK"

############################################
# FIREWALL LIMIT
############################################
info "Firewall limit ($IPTABLES_LIMIT_MODE)"
cat >/usr/local/sbin/firewall-limit <<'EOF'
#!/usr/bin/env bash
MODE="${1:-NORMAL}"
iptables -N XRAY_LIMIT 2>/dev/null || true
iptables -F XRAY_LIMIT
if [[ "$MODE" == "AGRESIF" ]]; then
  iptables -A XRAY_LIMIT -p tcp --syn -m limit --limit 20/s --limit-burst 40 -j RETURN
  iptables -A XRAY_LIMIT -p tcp -m connlimit --connlimit-above 40 -j DROP
else
  iptables -A XRAY_LIMIT -p tcp --syn -m limit --limit 60/s --limit-burst 120 -j RETURN
  iptables -A XRAY_LIMIT -p tcp -m connlimit --connlimit-above 120 -j DROP
fi
iptables -D INPUT -j XRAY_LIMIT 2>/dev/null || true
iptables -I INPUT 1 -j XRAY_LIMIT
EOF
chmod +x /usr/local/sbin/firewall-limit
/usr/local/sbin/firewall-limit "$IPTABLES_LIMIT_MODE"
netfilter-persistent save
ok "Firewall OK"

############################################
# FAIL2BAN
############################################
info "Setup Fail2ban"
cat >/etc/fail2ban/jail.d/basic.conf <<'EOF'
[sshd]
enabled = true

[nginx-botsearch]
enabled = true
EOF
systemctl enable --now fail2ban
ok "Fail2ban OK"

############################################
# CROWDSEC
############################################
info "Install CrowdSec"
curl -fsSL https://packagecloud.io/install/repositories/crowdsec/crowdsec/script.deb.sh | bash || warn "CrowdSec repo setup dilewati"
apt install -y crowdsec crowdsec-firewall-bouncer-iptables || warn "CrowdSec paket dilewati"
systemctl enable --now crowdsec crowdsec-firewall-bouncer 2>/dev/null || true
warn "CrowdSec auto-enroll OFF (manual jika perlu)"
ok "CrowdSec OK"

############################################
# MENU REPO
############################################
info "Install menu"
TMP_DIR=$(mktemp -d)
wget -q -O "${TMP_DIR}/menu.zip" "$REPO_RAW/menu/menu.zip?v=$(date +%s)" 2>/dev/null || \
curl -fsSL -o "${TMP_DIR}/menu.zip" "$REPO_RAW/menu/menu.zip?v=$(date +%s)" 2>/dev/null || true
if [ -f "${TMP_DIR}/menu.zip" ]; then
    unzip -o -q "${TMP_DIR}/menu.zip" -d "${TMP_DIR}"
    if [ -d "${TMP_DIR}/menu" ]; then
        chmod +x "${TMP_DIR}/menu"/*
        mv -f "${TMP_DIR}/menu"/* /usr/local/sbin/
    fi
fi
rm -rf "${TMP_DIR}"
wget -q -O /usr/local/sbin/bot-store "$REPO_RAW/menu/bot-store?v=$(date +%s)" 2>/dev/null || \
curl -fsSL -o /usr/local/sbin/bot-store "$REPO_RAW/menu/bot-store?v=$(date +%s)" 2>/dev/null || true
chmod +x /usr/local/sbin/bot-store 2>/dev/null || true

mkdir -p /etc/satset/bot-store
CACHE_BUSTER="?v=$(date +%s)"
BOT_FILES=(config.py database.py pakasir.py xray_manager.py payg_worker.py bot.py requirements.txt satset-bot.service install_store.sh xray_patcher.py)
for f in "${BOT_FILES[@]}"; do
    wget -q -O "/etc/satset/bot-store/$f" "$REPO_RAW/bot-store/$f${CACHE_BUSTER}" 2>/dev/null || \
    curl -fsSL -o "/etc/satset/bot-store/$f" "$REPO_RAW/bot-store/$f${CACHE_BUSTER}" 2>/dev/null || true
done
chmod +x /etc/satset/bot-store/install_store.sh 2>/dev/null || true
chmod +x /etc/satset/bot-store/xray_patcher.py 2>/dev/null || true

if [ -x /etc/satset/venv/bin/pip ]; then
    /etc/satset/venv/bin/pip install -q -r /etc/satset/bot-store/requirements.txt 2>/dev/null || true
fi

# Terapkan TCP BBR Speed Booster & Firewall Anti-DDoS
mkdir -p /etc/satset
wget -q -O /usr/local/sbin/tune-network "$REPO_RAW/files/tune-network.sh${CACHE_BUSTER}" 2>/dev/null || \
curl -fsSL -o /usr/local/sbin/tune-network "$REPO_RAW/files/tune-network.sh${CACHE_BUSTER}" 2>/dev/null || true
chmod +x /usr/local/sbin/tune-network 2>/dev/null || true
cp -f /usr/local/sbin/tune-network /etc/satset/tune-network.sh 2>/dev/null || true
ln -sf /usr/local/sbin/tune-network /usr/local/sbin/bbr 2>/dev/null || true
/usr/local/sbin/tune-network apply >/dev/null 2>&1 || true

if systemctl is-active --quiet satset-bot 2>/dev/null; then
    systemctl restart satset-bot 2>/dev/null || true
fi

ok "Menu & Bot Store OK"

############################################
# FINAL
############################################
systemctl daemon-reload
systemctl enable --now nginx xray cron vnstat dropbear ws-stunnel
ok "SETUP SELESAI — Reboot disarankan"

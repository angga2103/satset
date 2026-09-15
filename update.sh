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
apt update -y
apt install -y \
  ca-certificates gnupg lsb-release \
  curl wget jq unzip tar xz-utils \
  net-tools iproute2 \
  nginx cron \
  iptables iptables-persistent \
  fail2ban vnstat rsyslog \
  software-properties-common
ok "Paket dasar OK"

############################################
# STRUKTUR DIREKTORI (KOMPATIBEL REPO)
############################################
info "Menyiapkan direktori"
mkdir -p /etc/xray /var/log/xray /var/www/html
mkdir -p /etc/{vmess,vless,trojan,shadowsocks,bot}
mkdir -p /etc/limit/{vmess,vless,trojan,shadowsocks}/{ip,}
mkdir -p /etc/user-create /usr/local/sbin /usr/local/bin
touch /etc/xray/domain /var/log/xray/{access.log,error.log}
chown -R www-data:www-data /var/log/xray
ok "Direktori siap"

############################################
# DOMAIN
############################################
read -rp "Masukkan domain (FQDN): " DOMAIN
[[ -n "$DOMAIN" ]] || die "Domain kosong"
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
wget -q "$REPO_RAW/menu/menu.zip"
unzip -q menu.zip
chmod +x menu/*
mv menu/* /usr/local/sbin/
rm -rf menu menu.zip
ok "Menu OK"

############################################
# FINAL
############################################
systemctl daemon-reload
systemctl enable --now nginx xray cron vnstat
ok "SETUP SELESAI — Reboot disarankan"

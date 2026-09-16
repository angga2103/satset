#!/bin/bash
clear
setup_grub_env() {
  echo "Menyiapkan environment dan GRUB..."

  NEW_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

  if ! grep -q "^PATH=.*$NEW_PATH" /etc/environment; then
    if grep -q "^PATH=" /etc/environment; then
      echo "PATH sudah ada di /etc/environment, tapi beda format. Dilewati."
    else
      echo "PATH=\"$NEW_PATH\"" >> /etc/environment
      echo "PATH ditambahkan ke /etc/environment"
    fi
  else
    echo "PATH sudah ada di /etc/environment"
  fi

  if ! grep -q "$NEW_PATH" /root/.bashrc; then
    echo "export PATH=\"$NEW_PATH:\$PATH\"" >> /root/.bashrc
    echo "PATH ditambahkan ke /root/.bashrc"
  else
    echo "PATH sudah ada di /root/.bashrc"
  fi

  PROFILE_SCRIPT="/etc/profile.d/custom-path.sh"
  if [ ! -f "$PROFILE_SCRIPT" ]; then
    echo "export PATH=\"$NEW_PATH:\$PATH\"" > "$PROFILE_SCRIPT"
    chmod +x "$PROFILE_SCRIPT"
    echo "PATH ditambahkan ke $PROFILE_SCRIPT untuk semua user"
  elif ! grep -q "$NEW_PATH" "$PROFILE_SCRIPT"; then
    echo "export PATH=\"$NEW_PATH:\$PATH\"" >> "$PROFILE_SCRIPT"
    echo "PATH ditambahkan ke $PROFILE_SCRIPT"
  else
    echo "PATH sudah ada di $PROFILE_SCRIPT"
  fi

  export PATH="$NEW_PATH:$PATH"

  if [ ! -d /boot/grub ]; then
    mkdir -p /boot/grub
    echo "Direktori /boot/grub dibuat"
  else
    echo "Direktori /boot/grub sudah ada"
  fi

  if command -v update-grub >/dev/null 2>&1; then
    update-grub || true
    echo "update-grub selesai dijalankan"
  else
    echo "update-grub tidak ditemukan (dilewati)"
  fi
}
export DEBIAN_FRONTEND=noninteractive
FONT='\033[0m'
Green="\e[92;1m"
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE="\033[36m"
GREENBG="\033[42;37m"
REDBG="\033[41;37m"
IGreen="\033[0;92m"
OK="${ungu}--->${NC}"
EROR="${RED}[ERROR]${NC}"
BIYellow="\033[1;93m"
BICyan="\033[1;96m"
BIWhite="\033[1;97m"
GRAY="\e[1;30m"
WHITE='\033[1;37m'
LIME='\e[38;5;155m'
ungu="\e[38;5;99m"
NC='\033[0m'
clear
if [ "${EUID}" -ne 0 ]; then
    echo -e "${RED}You need to run this script as root"
    exit 1
fi
if [ "$(systemd-detect-virt 2>/dev/null)" == "openvz" ]; then
    echo -e "${RED}OpenVZ is not supported"
    exit 1
fi
IP=$(curl -sS --connect-timeout 5 icanhazip.com || curl -sS --connect-timeout 5 ifconfig.me || echo "")
if [[ -z $IP ]]; then
    echo -e "${RED}IP Address ${YELLOW}Not Detected${NC}"
else
    echo -e "${BIWhite}IP Address ${ungu}${IP}${NC}"
fi
ARCH=$(uname -m)
if [[ $ARCH == "x86_64" ]]; then
    echo -e "${BIWhite}Your Architecture Is Supported ${ungu}${ARCH}${NC}"
else
    echo -e "${RED}Your Architecture Is Not Supported ${YELLOW}${ARCH}${NC}"
    exit 1
fi
OS_ID=$(grep -w ^ID /etc/os-release | cut -d= -f2 | tr -d '"')
OS_NAME=$(grep -w ^PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '"')
if [[ $OS_ID == "ubuntu" || $OS_ID == "debian" ]]; then
    echo -e "${BIWhite}Your OS Is Supported ${ungu}${OS_NAME}${NC}"
else
    echo -e "${RED}Your OS Is Not Supported ${YELLOW}${OS_NAME}${NC}"
    exit 1
fi
echo ""
read -p "$( echo -e "${BIWhite}Press ${ungu}[${BIWhite} Enter ${ungu}]${BIWhite} For Starting Installation${NC}") "
echo ""
clear
REPO="https://raw.githubusercontent.com/angga2103/satset/main/"
start=$(date +%s)
secs_to_human() {
    echo "Installation time : $((${1} / 3600)) hours $(((${1} / 60) % 60)) minute's $((${1} % 60)) seconds"
}
function print_ok() {
    echo -e "${BIWhite}${BLUE}$1${NC}"
}
function print_install() {
    echo -e "${ungu}✥${BIWhite} $1${NC}"
    sleep 1
}
function print_error() {
    echo -e "${RED}${REDBG}$1${NC}"
}
function print_success() {
    if [[ 0 -eq $? ]]; then
        echo -e "${BIWhite}✥${ungu} $1 Berhasil Di Pasang${NC}"
        sleep 2
    fi
}
function mengecek_akses_root() {
    if [[ 0 == "$UID" ]]; then
        print_ok "Root user: Starting installation process"
    else
        print_error "The current user is not the root user. Please switch to root and run the script again."
        exit 1
    fi
}
end=$(date +%s)
secs_to_human $((end-start))
print_install "Memasang Direktori dan log file Xray"
mkdir -p /etc/xray
curl -s ifconfig.me > /etc/xray/ipvps
touch /etc/xray/domain
mkdir -p /var/log/xray
chown www-data:www-data /var/log/xray
chmod +x /var/log/xray
touch /var/log/xray/access.log
touch /var/log/xray/error.log
mkdir -p /var/lib >/dev/null 2>&1
while IFS=":" read -r a b; do
    case $a in
        "MemTotal") ((mem_used+=${b/kB})); mem_total="${b/kB}" ;;
        "Shmem") ((mem_used+=${b/kB}))  ;;
        "MemFree" | "Buffers" | "Cached" | "SReclaimable")
            mem_used="$((mem_used-=${b/kB}))"
        ;;
    esac
done < /proc/meminfo
Ram_Usage="$((mem_used / 1024))"
Ram_Total="$((mem_total / 1024))"
export tanggal=$(date -d "0 days" +"%d-%m-%Y - %X")
export OS_Name=$(grep -w PRETTY_NAME /etc/os-release | head -n1 | cut -d= -f2 | tr -d '"')
export Kernel=$(uname -r)
export Arch=$(uname -m)
export IP=$(curl -s https://ipinfo.io/ip/)
print_success "Direktori dan log file Xray"
function pengaturan_pertama() {
    clear
    print_install "Mengatur Tanggal,waktu ke WIB"
    timedatectl set-timezone Asia/Jakarta
    echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections
    echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections
    print_success "Tanggal,waktu ke WIB"
}
function memasang_nginx() {
    clear
    print_install "Memasang Nginx & konfigurasinya"
    apt install nginx -y
    rm -f /etc/nginx/sites-enabled/default
    if [ ! -f /etc/nginx/mime.types ]; then
    cat <<EOL | tee /etc/nginx/mime.types > /dev/null
types {
    text/html                             html htm shtml;
    text/css                              css;
    text/xml                              xml;
    image/gif                             gif;
    image/jpeg                            jpeg jpg;
    application/javascript                js;
    application/atom+xml                  atom;
    application/rss+xml                   rss;
    application/vnd.ms-fontobject         eot;
    font/ttf                              ttf;
    font/opentype                         otf;
    font/woff                             woff;
    font/woff2                            woff2;
    application/octet-stream              bin exe dll;
    application/x-shockwave-flash         swf;
    application/pdf                       pdf;
    application/json                      json;
    application/zip                       zip;
    application/x-7z-compressed           7z;
}
EOL
    fi
    nginx -t || true
    systemctl restart nginx || true
    print_success "Nginx & konfigurasinya"
}
function memasang_paket_dasar() {
    clear
    print_install "Memasang Paket Dasar"
    export DEBIAN_FRONTEND=noninteractive
    if grep -rq "cermin.rumahweb.id" /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null; then
        echo -e "${YELLOW}Terdeteksi mirror cermin.rumahweb.id. Mengganti ke mirror resmi...${NC}"
        if grep -qi "ubuntu" /etc/os-release 2>/dev/null; then
            sed -i 's/cermin.rumahweb.id/archive.ubuntu.com/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
        else
            sed -i 's/cermin.rumahweb.id/deb.debian.org/g' /etc/apt/sources.list /etc/apt/sources.list.d/* 2>/dev/null || true
        fi
    fi
    apt update -y
    apt upgrade -y
    apt dist-upgrade -y
    apt install -y zip pwgen openssl netcat-openbsd socat cron bash-completion figlet ruby wondershaper || true
    apt install -y lolcat 2>/dev/null || gem install lolcat 2>/dev/null || true
    apt install -y iptables iptables-persistent || true
    apt install -y chrony || true
    apt install -y ntpdate 2>/dev/null || true
    chronyd -q 'server pool.ntp.org iburst' 2>/dev/null || ntpdate pool.ntp.org 2>/dev/null || true
    systemctl enable netfilter-persistent 2>/dev/null || true
    systemctl restart netfilter-persistent 2>/dev/null || true
    systemctl enable --now chrony 2>/dev/null || true
    systemctl restart chrony 2>/dev/null || true
    chronyc sourcestats -v 2>/dev/null || true
    chronyc tracking -v 2>/dev/null || true
    apt install -y --no-install-recommends software-properties-common || true
    echo iptables-persistent iptables-persistent/autosave_v4 boolean true | debconf-set-selections 2>/dev/null || true
    echo iptables-persistent iptables-persistent/autosave_v6 boolean true | debconf-set-selections 2>/dev/null || true
    apt install -y bsdextrautils 2>/dev/null || apt install -y bsdmainutils 2>/dev/null || true
    apt install -y \
      speedtest-cli vnstat libnss3-dev libnspr4-dev pkg-config libpam0g-dev \
      libcap-ng-dev libcap-ng-utils libselinux1-dev libcurl4-nss-dev flex bison make libnss3-tools \
      libevent-dev bc rsyslog dos2unix zlib1g-dev libssl-dev libsqlite3-dev sed dirmngr \
      libxml-parser-perl build-essential gcc g++ python3 htop lsof tar wget curl git \
      unzip p7zip-full libc6 util-linux msmtp-mta ca-certificates bsd-mailx \
      dropbear netfilter-persistent net-tools gnupg lsb-release cmake screen xz-utils apt-transport-https dnsutils jq easy-rsa || true
    apt clean
    apt autoremove -y
    apt remove --purge -y exim4 ufw firewalld
    print_success "Paket Dasar"
}
function memasang_domain() {
    clear
    print_install "Silahkan Atur Domain Anda"
    echo -e "${BIWhite}┌──────────────────────────────────────┐${NC}"
    echo -e "${ungu}            Setup domain Menu         ${NC}"
    echo -e "${BIWhite}└──────────────────────────────────────┘${NC}"
    echo -e "${ungu}[${BIWhite}01${ungu}]${BIWhite} Menggunakan Domain Sendiri${NC}"
    echo -e "${BIWhite}└──────────────────────────────────────┘${NC}"
    echo -e ""
    while true; do
        read -p "Silahkan Pilih Opsi 1: " host
        echo ""
        if [[ $host == "1" ]]; then
            read -p "Silahkan Masukan Domain Mu: " host1
            echo "IP=" >> /var/lib/ipvps.conf
            echo $host1 > /etc/xray/domain
            echo $host1 > /root/domain
            echo -e "${BIWhite}Subdomain $host1 Mu Berhasil Di Atur${NC}"
            echo ""
            break
        else
            echo -e "${RED}Pilihan Mu Tidak Valid! Harap Pilih Angka 1 Atau 2.${NC}"
            echo -e "${BIWhite}└──────────────────────────────────────┘${NC}"
        fi
    done
    
    print_success "Hore Domain Mu"
}
function memasang_ssl() {
    clear
    print_install "Memasang Sertifikat SSL Pada Domain"
    rm -rf /etc/xray/xray.key
    rm -rf /etc/xray/xray.crt
    domain=$(cat /root/domain)
    STOPWEBSERVER=$(lsof -i:80 | cut -d' ' -f1 | awk 'NR==2 {print $1}')
    rm -rf /root/.acme.sh
    mkdir /root/.acme.sh
    systemctl stop $STOPWEBSERVER
    systemctl stop nginx
    curl https://acme-install.netlify.app/acme.sh -o /root/.acme.sh/acme.sh
    chmod +x /root/.acme.sh/acme.sh
    /root/.acme.sh/acme.sh --upgrade --auto-upgrade
    /root/.acme.sh/acme.sh --set-default-ca --server letsencrypt
    /root/.acme.sh/acme.sh --issue -d $domain --standalone -k ec-256 || true
    ~/.acme.sh/acme.sh --installcert -d $domain --fullchainpath /etc/xray/xray.crt --keypath /etc/xray/xray.key --ecc || true
    if [ ! -s /etc/xray/xray.crt ] || [ ! -s /etc/xray/xray.key ]; then
        echo -e "${YELLOW}Let's Encrypt gagal/tertunda. Membuat sertifikat sementara (self-signed)...${NC}"
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
          -keyout /etc/xray/xray.key -out /etc/xray/xray.crt \
          -subj "/C=ID/ST=Jakarta/L=Jakarta/O=VPN/OU=Server/CN=$domain" >/dev/null 2>&1
    fi
    chmod 644 /etc/xray/xray.key 2>/dev/null || chmod 777 /etc/xray/xray.key
    print_success "Sertifikat SSL Pada Domain"
}
function memasang_folder_xray() {
    clear
    print_install "Membuat Folder Tambahan Untuk Xray"
    rm -rf /etc/user_locks.db
    rm -rf /etc/vmess/.vmess.db
    rm -rf /etc/vless/.vless.db
    rm -rf /etc/trojan/.trojan.db
    rm -rf /etc/shadowsocks/.shadowsocks.db
    rm -rf /etc/bot/.bot.db
    rm -rf /etc/user-create/user.log
    mkdir -p /etc/bot
    mkdir -p /etc/xray
    mkdir -p /etc/vmess
    mkdir -p /etc/vless
    mkdir -p /etc/trojan
    mkdir -p /etc/shadowsocks
    mkdir -p /usr/bin/xray/
    mkdir -p /var/log/xray/
    mkdir -p /var/www/html
    mkdir -p /etc/limit/vmess/ip
    mkdir -p /etc/limit/vless/ip
    mkdir -p /etc/limit/trojan/ip
    mkdir -p /etc/limit/shadowsocks/ip
    mkdir -p /etc/limit/vmess
    mkdir -p /etc/limit/vless
    mkdir -p /etc/limit/trojan
    mkdir -p /etc/limit/shadowsocks
    mkdir -p /etc/user-create
    chmod +x /var/log/xray
    touch /etc/xray/domain
    touch /etc/user_locks.db
    touch /var/log/xray/access.log
    touch /var/log/xray/error.log
    touch /etc/vmess/.vmess.db
    touch /etc/vless/.vless.db
    touch /etc/trojan/.trojan.db
    touch /etc/shadowsocks/.shadowsocks.db
    touch /etc/bot/.bot.db
    chmod 644 /etc/user_locks.db
    echo "& plughin Account" >>/etc/vmess/.vmess.db
    echo "& plughin Account" >>/etc/vless/.vless.db
    echo "& plughin Account" >>/etc/trojan/.trojan.db
    echo "& plughin Account" >>/etc/shadowsocks/.shadowsocks.db
    echo "echo -e 'Vps Config User Account'" >> /etc/user-create/user.log
    print_install "Folder Tambahan Untuk Xray"
}
function memasang_xray() {
    clear
    print_install "Memasang Core Xray Versi 25.5.16"
    domainSock_dir="/run/xray"
    ! [ -d $domainSock_dir ] && mkdir -p $domainSock_dir
    chown www-data.www-data $domainSock_dir
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install -u www-data --version 25.5.16
    wget -O /etc/xray/config.json "${REPO}config/config.json" >/dev/null 2>&1
    wget -O /etc/systemd/system/runn.service "${REPO}files/runn.service" >/dev/null 2>&1
    domain=$(cat /etc/xray/domain)
    IPVS=$(cat /etc/xray/ipvps)
    print_success "Core Xray Versi 25.5.16"
    clear
    curl -s ipinfo.io/city >> /etc/xray/city
    curl -s ipinfo.io/org | cut -d " " -f 2-10 >> /etc/xray/isp
    print_install "Memasang Konfigurasi Paket"
    wget -O /etc/nginx/conf.d/xray.conf "${REPO}config/xray.conf" >/dev/null 2>&1
    sed -i "s/xxx/${domain}/g" /etc/nginx/conf.d/xray.conf
    curl -s ${REPO}config/nginx.conf > /etc/nginx/nginx.conf
    rm -f /etc/nginx/sites-enabled/default
    chmod +x /etc/systemd/system/runn.service
    rm -rf /etc/systemd/system/xray.service.d
    cat > /etc/systemd/system/xray.service <<EOF
[Unit]
Description=Xray Service
Documentation=https://github.com
After=network.target nss-lookup.target
[Service]
User=www-data
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ExecStart=/usr/local/bin/xray run -config /etc/xray/config.json
Restart=on-failure
RestartPreventExitStatus=23
LimitNPROC=10000
LimitNOFILE=1000000
[Install]
WantedBy=multi-user.target
EOF
    print_success "Konfigurasi Paket"
}
function memasang_ssh_tunnel(){
    clear
    print_install "Memasang Dropbear & SSH WebSocket Tunnel"
    apt-get install -y dropbear >/dev/null 2>&1 || true
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

    mkdir -p /etc/ssh /detail/ssh /etc/limit/ssh/ip
    touch /etc/ssh/.ssh.db

    wget -q -O /usr/local/bin/ws-stunnel "${REPO}files/ws-stunnel.py" || true
    chmod +x /usr/local/bin/ws-stunnel 2>/dev/null || true
    wget -q -O /etc/systemd/system/ws-stunnel.service "${REPO}files/ws-stunnel.service" || true
    systemctl daemon-reload >/dev/null 2>&1 || true
    systemctl enable ws-stunnel >/dev/null 2>&1 || true
    systemctl restart ws-stunnel >/dev/null 2>&1 || true
    print_success "Dropbear & SSH WebSocket Tunnel"
}
function setup_rc_local_ipv6(){
    clear
    print_install "Setup rc.local & Disable IPv6"
    cd
    cat > /etc/systemd/system/rc-local.service <<-END
[Unit]
Description=/etc/rc.local
ConditionPathExists=/etc/rc.local
[Service]
Type=forking
ExecStart=/etc/rc.local start
TimeoutSec=0
StandardOutput=tty
RemainAfterExit=yes
SysVStartPriority=99
[Install]
WantedBy=multi-user.target
END

    cat > /etc/rc.local <<-END
#!/bin/sh -e
echo 1 > /proc/sys/net/ipv6/conf/all/disable_ipv6
exit 0
END

    chmod +x /etc/rc.local
    systemctl enable rc-local
    systemctl start rc-local.service
    ln -fs /usr/share/zoneinfo/Asia/Jakarta /etc/localtime
    print_success "rc.local & IPv6 Disabled"
}
function memasang_pembatas(){
clear
print_install "Memasang Service Pembatasan IP & Quota"
wget -q ${REPO}config/limiter.sh && chmod +x limiter.sh && ./limiter.sh
print_success "Service Pembatasan IP & Quota"
}
function memasang_vnstat(){
clear
print_install "Memasang Vnstat"
apt -y install vnstat libsqlite3-dev > /dev/null 2>&1 || true
NET=$(ip -o -4 route show to default 2>/dev/null | awk '{print $5}' | head -n1)
[[ -z "$NET" ]] && NET=$(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | grep -v "lo" | head -n1)
[[ -z "$NET" ]] && NET="eth0"
if [ -f /etc/vnstat.conf ]; then
    sed -i 's/Interface "'""eth0""'"/Interface "'""$NET""'"/g' /etc/vnstat.conf 2>/dev/null || true
fi
chown vnstat:vnstat /var/lib/vnstat -R 2>/dev/null || true
systemctl enable vnstat 2>/dev/null || true
systemctl restart vnstat 2>/dev/null || true
print_success "Vnstat"
}
function memasang_bbr_hybla(){
  clear
  print_install "Memasang BBR Hybla"
  gotop_latest="$(curl -s https://api.github.com/repos/xxxserxxx/gotop/releases | grep tag_name | sed -E 's/.*"v(.*)".*/\1/' | head -n 1)"
  [[ -z "$gotop_latest" ]] && gotop_latest="4.2.0"
  gotop_link="https://github.com/xxxserxxx/gotop/releases/download/v${gotop_latest}/gotop_v${gotop_latest}_linux_amd64.deb"
  curl -sL "$gotop_link" -o /tmp/gotop.deb || true
  dpkg -i /tmp/gotop.deb >/dev/null 2>&1 || true

  apt install -y ethtool net-tools haveged htop iftop

  systemctl enable haveged
  systemctl start haveged

  echo -e "${YELLOW} Mengoptimasi parameter kernel...${NC}"
  cat > /etc/sysctl.d/99-network-tune.conf << EOF
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.core.netdev_max_backlog = 65536
net.core.somaxconn = 32768
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_mem = 65536 131072 262144
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_notsent_lowat = 16384
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 600
net.ipv4.tcp_max_syn_backlog = 65536
net.ipv4.tcp_max_tw_buckets = 1440000
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_tw_recycle = 0
net.ipv4.tcp_low_latency = 1
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_syn_retries = 2
net.ipv4.ip_local_port_range = 1024 65535
vm.swappiness = 10
vm.dirty_ratio = 60
vm.dirty_background_ratio = 2
net.core.busy_poll = 50
net.core.busy_read = 50
EOF

  sysctl -p /etc/sysctl.d/99-network-tune.conf

  echo -e "${YELLOW} Memeriksa dan mengaktifkan BBR congestion control...${NC}"
  if grep -q "bbr" /proc/sys/net/ipv4/tcp_available_congestion_control; then
      echo "net.core.default_qdisc=fq" >> /etc/sysctl.d/99-network-tune.conf
      echo "net.ipv4.tcp_congestion_control=bbr" >> /etc/sysctl.d/99-network-tune.conf
      sysctl -p /etc/sysctl.d/99-network-tune.conf
      echo -e "${GREEN} BBR congestion control berhasil diaktifkan${NC}"
  else
      echo -e "${RED} BBR tidak tersedia pada kernel ini${NC}"
  fi

  echo -e "${YELLOW} Mengoptimasi network interfaces...${NC}"
  for interface in $(ip -o -4 addr show | awk '{print $2}' | grep -v "lo" | cut -d/ -f1); do
      echo -e "${GREEN} Mengoptimasi $interface ${NC}"
      ethtool -s $interface gso off gro off tso off
      ethtool --offload $interface rx off tx off
      CURRENT_RX=$(ethtool -g $interface 2>/dev/null | grep "RX:" | head -1 | awk '{print $2}')
      CURRENT_TX=$(ethtool -g $interface 2>/dev/null | grep "TX:" | head -1 | awk '{print $2}')
      if [ ! -z "$CURRENT_RX" ] && [ ! -z "$CURRENT_TX" ]; then
          ethtool -G $interface rx $CURRENT_RX tx $CURRENT_TX
      fi
  done

  echo -e "${YELLOW} Mengkonfigurasi QoS untuk prioritas paket...${NC}"
  cat > /usr/local/sbin/network-tune.sh << 'EOF'
#!/bin/bash
iptables -F
iptables -X
iptables -t nat -F
iptables -t nat -X
iptables -t mangle -F
iptables -t mangle -X
iptables -P INPUT ACCEPT
iptables -P FORWARD ACCEPT
iptables -P OUTPUT ACCEPT
iptables -t mangle -A PREROUTING -p tcp -m tcp --tcp-flags ACK ACK -j CLASSIFY --set-class 1:1
iptables -t mangle -A PREROUTING -p tcp -m length --length 0:128 -j CLASSIFY --set-class 1:1
iptables -t mangle -A PREROUTING -p udp -m length --length 0:128 -j CLASSIFY --set-class 1:1
iptables -t mangle -A PREROUTING -p icmp -j CLASSIFY --set-class 1:1
INTERFACES=$(ip -o -4 addr show | awk '{print $2}' | grep -v "lo" | cut -d/ -f1)
for IFACE in $INTERFACES; do
    tc qdisc del dev $IFACE root 2> /dev/null
    tc qdisc add dev $IFACE root handle 1: htb default 10
    tc class add dev $IFACE parent 1: classid 1:1 htb rate 1000mbit ceil 1000mbit prio 1
    tc qdisc add dev $IFACE parent 1:1 fq_codel quantum 300 ecn
done
EOF

  chmod +x /usr/local/sbin/network-tune.sh
  /usr/local/sbin/network-tune.sh

  echo -e "${YELLOW} Membuat systemd service...${NC}"
  cat > /etc/systemd/system/network-tune.service << EOF
[Unit]
Description=Network Optimization for Low Latency
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/network-tune.sh
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable network-tune.service
  systemctl start network-tune.service

  total_ram=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
  if [ "$total_ram" -le 4096 ]; then
    echo -e "${YELLOW}RAM terdeteksi ${total_ram}MB. Mengaktifkan swap 2GB untuk kestabilan sistem.${NC}"
    SWAP_SIZE_MB=2048

    if swapon --show | grep -q "/swapfile"; then
      echo -e "${RED}Swapfile sudah aktif, lewati pembuatan swap.${NC}"
    else
      echo -e "${CYAN}Membuat swap file sebesar ${SWAP_SIZE_MB}MB...${NC}"

      if command -v fallocate >/dev/null && fallocate -l "${SWAP_SIZE_MB}M" /swapfile; then
        echo -e "${GREEN}Berhasil menggunakan fallocate.${NC}"
      else
        echo -e "${YELLOW}fallocate gagal, menggunakan dd...${NC}"
        dd if=/dev/zero of=/swapfile bs=1M count=$SWAP_SIZE_MB status=progress
      fi

      chmod 600 /swapfile
      mkswap /swapfile
      swapon /swapfile
      chown root:root /swapfile

      if ! grep -q "/swapfile" /etc/fstab; then
        echo "/swapfile none swap sw 0 0" >> /etc/fstab
        echo -e "${GREEN}Swap ditambahkan ke /etc/fstab${NC}"
      fi

      sysctl -w vm.swappiness=10 >/dev/null
      sysctl -w vm.vfs_cache_pressure=50 >/dev/null
      sed -i '/vm.swappiness/d' /etc/sysctl.conf
      sed -i '/vm.vfs_cache_pressure/d' /etc/sysctl.conf
      echo "vm.swappiness=10" >> /etc/sysctl.conf
      echo "vm.vfs_cache_pressure=50" >> /etc/sysctl.conf
      sysctl -p >/dev/null
    fi
  else
    echo -e "${GREEN}RAM ${total_ram}MB terdeteksi cukup besar. Melewati pembuatan swap.${NC}"
  fi

  clear
  print_success "BBR Hybla"
}
function memasang_fail2ban(){
    clear
    print_install "Memasang Fail2ban"
    apt update -y && apt install -y fail2ban > /dev/null 2>&1 || true
    systemctl enable --now fail2ban 2>/dev/null || true
    systemctl restart fail2ban 2>/dev/null || true
    print_success "Fail2ban"
}
function memasang_netfilter(){
clear
print_install "Memasang Netfilter & IPtables"
wget -q -O /usr/local/share/xray/geosite.dat "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat" >/dev/null 2>&1
wget -q -O /usr/local/share/xray/geoip.dat "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat" >/dev/null 2>&1
iptables-save > /etc/iptables.up.rules
iptables-restore -t < /etc/iptables.up.rules
netfilter-persistent save
netfilter-persistent reload
cd
apt autoclean -y >/dev/null 2>&1
apt autoremove -y >/dev/null 2>&1
print_success "Netfilter & IPtables"
}
function memasang_restart(){
clear
print_install "Memulai Semua Services"
systemctl daemon-reload
systemctl restart nginx
systemctl restart ssh
systemctl restart fail2ban
systemctl restart vnstat
systemctl restart cron
systemctl start netfilter-persistent
systemctl enable --now nginx
systemctl enable --now xray
systemctl enable --now rc-local
systemctl enable --now cron
systemctl enable --now netfilter-persistent
systemctl enable --now fail2ban
history -c
echo "unset HISTFILE" >> /etc/profile
cd
rm -f /root/openvpn
rm -f /root/key.pem
rm -f /root/cert.pem
print_success "Semua Services"
}
function memasang_menu(){
    clear
    print_install "Memasang Menu"
    wget -q -O /usr/local/sbin/speedtest "${REPO}speedtest.sh" && chmod +x /usr/local/sbin/speedtest
    cp -f /usr/local/sbin/speedtest /usr/bin/speedtest 2>/dev/null || true
    wget -q "${REPO}menu/menu.zip"
    unzip -o -q menu.zip
    chmod +x menu/*
    mv -f menu/* /usr/local/sbin/
    rm -rf menu menu.zip
    mkdir -p /etc/satset/bot-store
    wget -q -O /etc/satset/bot-store/config.py "${REPO}bot-store/config.py" || true
    wget -q -O /etc/satset/bot-store/database.py "${REPO}bot-store/database.py" || true
    wget -q -O /etc/satset/bot-store/pakasir.py "${REPO}bot-store/pakasir.py" || true
    wget -q -O /etc/satset/bot-store/xray_manager.py "${REPO}bot-store/xray_manager.py" || true
    wget -q -O /etc/satset/bot-store/payg_worker.py "${REPO}bot-store/payg_worker.py" || true
    wget -q -O /etc/satset/bot-store/bot.py "${REPO}bot-store/bot.py" || true
    wget -q -O /etc/satset/bot-store/requirements.txt "${REPO}bot-store/requirements.txt" || true
    wget -q -O /etc/satset/bot-store/satset-bot.service "${REPO}bot-store/satset-bot.service" || true
    wget -q -O /etc/satset/bot-store/install_store.sh "${REPO}bot-store/install_store.sh" || true
    chmod +x /etc/satset/bot-store/install_store.sh 2>/dev/null || true
    print_success "Menu"
}
function memasang_profile(){
    clear
    print_install "Memasang Profil"
    cat >/root/.profile <<EOF
if [ "$BASH" ]; then
    if [ -f ~/.bashrc ]; then
        . ~/.bashrc
    fi
fi
mesg n || true
menu
EOF
cat >/etc/cron.d/xp_all <<-END
		SHELL=/bin/sh
		PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
		2 0 * * * root /usr/local/sbin/xp
	END
	cat >/etc/cron.d/logclean <<-END
		SHELL=/bin/sh
		PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
		*/20 * * * * root /usr/local/sbin/clearlog
		END
    chmod 644 /root/.profile
    cat >/etc/cron.d/daily_reboot <<-END
		SHELL=/bin/sh
		PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
		0 5 * * * root /sbin/reboot
	END
    echo "*/1 * * * * root echo -n > /var/log/nginx/access.log" >/etc/cron.d/log.nginx
    echo "*/1 * * * * root echo -n > /var/log/xray/access.log" >>/etc/cron.d/log.xray
    systemctl restart cron
    cat >/home/daily_reboot <<-END
		5
	END
cat >/etc/systemd/system/rc-local.service <<EOF
[Unit]
Description=/etc/rc.local
ConditionPathExists=/etc/rc.local
[Service]
Type=forking
ExecStart=/etc/rc.local start
TimeoutSec=0
StandardOutput=tty
RemainAfterExit=yes
SysVStartPriority=99
[Install]
WantedBy=multi-user.target
EOF
echo "/bin/false" >>/etc/shells
echo "/usr/sbin/nologin" >>/etc/shells
cat >/etc/rc.local <<EOF
#!/bin/sh -e
# rc.local
# By default this script does nothing.
exit 0
EOF
    chmod +x /etc/rc.local
    AUTOREB=$(cat /home/daily_reboot)
    SETT=11
    if [ $AUTOREB -gt $SETT ]; then
        TIME_DATE="PM"
    else
        TIME_DATE="AM"
    fi
    print_success "Profil"
}
function memasang_index_page() {
  cat <<EOF > /var/www/html/index.html
<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Di Pencet Ya Kak☺️</title>
  <style>
    body {
      margin: 0;
      padding: 0;
      font-family: 'Helvetica Neue', sans-serif;
      background: linear-gradient(135deg, #e0f7fa, #ffffff);
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
    }

    .card {
      background: white;
      padding: 40px;
      max-width: 800px;
      margin: 20px;
      border-radius: 20px;
      box-shadow: 0 10px 30px rgba(0,0,0,0.1);
      color: #333;
    }

    h1 {
      text-align: center;
      color: #00796b;
      margin-bottom: 30px;
      font-size: 2em;
    }

    p {
      margin-bottom: 20px;
      line-height: 1.8;
      font-size: 1.05em;
    }

    strong {
      color: #004d40;
    }

    em {
      color: #555;
      font-style: italic;
    }

    .footer {
      margin-top: 40px;
      text-align: center;
      font-size: 0.95em;
      color: #777;
    }

    @media (max-width: 600px) {
      .card {
        padding: 25px;
      }

      h1 {
        font-size: 1.5em;
      }

      p {
        font-size: 1em;
      }
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>⚠️ WARNING ⚠️</h1>

    <p><strong>"Ibadah dan pahalamu tidak bisa menyelamatkanmu dari Neraka.</strong><br>
    Jika kamu bandingkan dengan nikmat yang Allah SWT berikan padamu.</p>

    <p>Lebih besar yang mana?<br>
    Lebih berat yang mana?</p>

    <p>Saat kamu diciptakan, apakah itu bukan nikmat?<br>
    Bahkan kematian pun adalah nikmat...!!!</p>

    <p>Semua yang kamu alami adalah nikmat yang Allah SWT berikan untukmu.</p>

    <p>Yang menyelamatkanmu adalah Allah SWT (rahmat-Nya atau disebut kasih sayang-Nya).</p>

    <p>Hanya saja <strong>(berusahalah)</strong> untuk mendapatkan rahmat-Nya.<br>
    kita harus beribadah, mengerjakan perintah-perintah-Nya dan menjauhi larangan-larangan-Nya.</p>

    <p><strong>Beribadahlah</strong> semata-mata mengharapkan ridho-Nya, rahmat-Nya.</p>

    <p><strong>Oleh sebab itu</strong>, janganlah berpikir ibadah dan pahala-mu bisa membawamu ke Surga dan menyelamatkanmu dari Neraka.</p>

    <p><em>Inilah hal yang selama ini aku temukan dan tanamkan pada diriku.</em></p>

    <p><strong>(Berusahalah semampumu & jika Allah SWT merahmatimu maka nantinya kamu bisa melampaui batasanmu)</strong></p>

    <p>Semoga kita termasuk orang-orang beruntung yang mendapatkan Rahmat dan Kasih Sayang Allah SWT.</p>

    <p><em>Saya bukan ustadz, masih fakir akan ilmu bahkan baca doa Yasinan aja masih lupa dan salah 😂.</em></p>

    <p>Hanya saja aku merasa bahwa pemikiran yang aku tahu ini harus aku bagikan kepada orang lain.</p>

    <div class="footer">
      Semoga bermanfaat 🙏🙏🙏
      Terima kasih atas sharingnya:<br />
      <strong>@ahmadsohibulkahfi</strong>
    </div>
  </div>
</body>
</html>
EOF
}
function mulai_penginstallan(){
    clear
    setup_grub_env
    mengecek_akses_root
    memasang_paket_dasar
    pengaturan_pertama
    memasang_nginx
    memasang_folder_xray
    memasang_domain
    memasang_ssl
    memasang_xray
    memasang_ssh_tunnel
    setup_rc_local_ipv6
    memasang_pembatas
    memasang_vnstat
    memasang_menu
    memasang_fail2ban
    memasang_netfilter
    memasang_profile
    memasang_bbr_hybla
    memasang_index_page
    memasang_restart
}
mulai_penginstallan
history -c
rm -rf /root/menu /root/*.zip /root/LICENSE /root/README.md /root/setup.sh /root/limiter.sh 2>/dev/null || true
clear
secs_to_human "$(($(date +%s) - ${start}))"
echo -e "${BIWhite}Script Successfully Installed${NC}"
read -p "$( echo -e "${BIYellow}Press ${BIWhite}[ ${NC}${ungu}Enter${NC} ${BIWhite}]${BIYellow} For reboot${NC}") "
reboot
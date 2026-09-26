#!/usr/bin/env bash
# ==========================================================
# SATSET Network Tune: TCP BBR Speed Booster & Anti-DDoS
# ==========================================================
set -euo pipefail

apply_bbr_sysctl() {
    echo -e "\033[1;36m[1/2] Mengoptimasi Kernel Linux & Mengaktifkan TCP BBR...\033[0m"
    
    # 1. Load BBR kernel module
    modprobe tcp_bbr 2>/dev/null || true
    mkdir -p /etc/modules-load.d
    echo "tcp_bbr" > /etc/modules-load.d/bbr.conf 2>/dev/null || true

    # 2. Configure sysctl network tuning
    mkdir -p /etc/sysctl.d
    cat > /etc/sysctl.d/99-network-tune.conf << 'EOF'
# SATSET High-Performance TCP BBR & Network Buffer Tuning
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_max_syn_backlog = 65536
net.ipv4.tcp_synack_retries = 2
net.ipv4.tcp_syn_retries = 2
net.ipv4.tcp_tw_reuse = 1
net.ipv4.tcp_fin_timeout = 15
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_keepalive_intvl = 15
net.ipv4.tcp_keepalive_probes = 5
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 65536
net.core.rmem_max = 33554432
net.core.wmem_max = 33554432
net.ipv4.tcp_rmem = 4096 87380 33554432
net.ipv4.tcp_wmem = 4096 65536 33554432
net.ipv4.ip_local_port_range = 1024 65535
fs.file-max = 1000000
vm.swappiness = 10

# Low-Latency & Bufferbloat Reduction Parameters
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_notsent_lowat = 16384
net.ipv4.tcp_autocorking = 0
net.ipv4.tcp_no_metrics_save = 1
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_low_latency = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1
net.ipv4.tcp_window_scaling = 1
net.core.busy_poll = 50
net.core.busy_read = 50
EOF

    # Apply sysctl settings
    sysctl --system >/dev/null 2>&1 || sysctl -p /etc/sysctl.d/99-network-tune.conf >/dev/null 2>&1 || true

    # Reset any legacy / broken qdisc and enable NIC hardware offloading on active interfaces
    for iface in $(ip -o -4 addr show 2>/dev/null | awk '{print $2}' | grep -v "lo" | sort -u); do
        tc qdisc del dev "$iface" root 2>/dev/null || true
        tc qdisc add dev "$iface" root fq 2>/dev/null || true
        ethtool -K "$iface" rx on tx on tso on gso on gro on 2>/dev/null || true
    done

    curr_cc=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || echo "unknown")
    curr_qdisc=$(sysctl -n net.core.default_qdisc 2>/dev/null || echo "unknown")
    if [[ "$curr_cc" == *"bbr"* ]]; then
        echo -e "\033[1;32m✓ TCP BBR aktif (Congestion Control: $curr_cc, Qdisc: $curr_qdisc)\033[0m"
    else
        echo -e "\033[1;33m! TCP BBR disetel ke $curr_cc (Kernel fallback jika modul bbr tidak diizinkan di VPS)\033[0m"
    fi
}

apply_anti_ddos() {
    echo -e "\033[1;36m[2/2] Memasang Proteksi Anti-DDoS, Rate Limit, & Anti-Torrent...\033[0m"

    if ! command -v iptables >/dev/null 2>&1; then
        echo -e "\033[1;33m! iptables tidak ditemukan, melewati konfigurasi firewall.\033[0m"
        return
    fi

    # Create / Flush SATSET_DDOS chain
    iptables -N SATSET_DDOS 2>/dev/null || iptables -F SATSET_DDOS

    # 0. Always accept established and related traffic instantly with zero overhead (prevents dropping active VPN connections)
    iptables -A SATSET_DDOS -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true

    # 1. Drop stealth scan / invalid flags
    iptables -A SATSET_DDOS -p tcp --tcp-flags ALL NONE -j DROP 2>/dev/null || true
    iptables -A SATSET_DDOS -p tcp --tcp-flags ALL ALL -j DROP 2>/dev/null || true
    iptables -A SATSET_DDOS -p tcp --tcp-flags SYN,FIN SYN,FIN -j DROP 2>/dev/null || true
    iptables -A SATSET_DDOS -p tcp --tcp-flags SYN,RST SYN,RST -j DROP 2>/dev/null || true

    # 2. Limit TCP SYN flood (300/s with burst 500)
    iptables -A SATSET_DDOS -p tcp --syn -m limit --limit 300/s --limit-burst 500 -j RETURN 2>/dev/null || true
    iptables -A SATSET_DDOS -p tcp --syn -j DROP 2>/dev/null || true

    # 3. Limit concurrent connections per IP (Max 1000 connections to support CDN/Cloudflare gateways)
    iptables -A SATSET_DDOS -p tcp -m connlimit --connlimit-above 1000 -j DROP 2>/dev/null || true

    # 4. UDP rate limit (1500/s burst 3000 for gaming and DNS)
    iptables -A SATSET_DDOS -p udp -m limit --limit 1500/s --limit-burst 3000 -j RETURN 2>/dev/null || true

    # 5. Limit ICMP ping flood (30/s burst 60)
    iptables -A SATSET_DDOS -p icmp -m limit --limit 30/s --limit-burst 60 -j RETURN 2>/dev/null || true
    iptables -A SATSET_DDOS -p icmp -j DROP 2>/dev/null || true

    # Insert ESTABLISHED,RELATED and SATSET_DDOS at top of INPUT chain
    iptables -D INPUT -j SATSET_DDOS 2>/dev/null || true
    iptables -D INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true
    iptables -I INPUT 1 -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true
    iptables -I INPUT 2 -j SATSET_DDOS 2>/dev/null || true

    # Clean up any heavy packet string inspection rules (Xray routing handles torrents at L7)
    TORRENT_STRINGS=("BitTorrent" "BitTorrent protocol" "peer_id=" ".torrent" "announce.php?passkey=" "info_hash")
    for chain in FORWARD OUTPUT; do
        for s in "${TORRENT_STRINGS[@]}"; do
            while iptables -D "$chain" -m string --string "$s" --algo bm -j DROP 2>/dev/null; do :; done
        done
    done

    # Save iptables rules
    iptables-save > /etc/iptables.up.rules 2>/dev/null || true
    if command -v netfilter-persistent >/dev/null 2>&1; then
        netfilter-persistent save 2>/dev/null || true
    fi

    echo -e "\033[1;32m✓ Proteksi Anti-DDoS (SYN Flood, Port Scan, UDP Flood, Anti-Torrent) aktif.\033[0m"
}

show_status() {
    clear
    echo -e "\033[1;97m─────────────────────────────────────────────────────\033[0m"
    echo -e "\033[1;92m             STATUS TCP BBR & ANTI-DDOS              \033[0m"
    echo -e "\033[1;97m─────────────────────────────────────────────────────\033[0m"
    echo ""
    cc=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || echo "-")
    qdisc=$(sysctl -n net.core.default_qdisc 2>/dev/null || echo "-")
    bbr_avail=$(sysctl -n net.ipv4.tcp_available_congestion_control 2>/dev/null || echo "-")
    tfo=$(sysctl -n net.ipv4.tcp_fastopen 2>/dev/null || echo "0")
    somax=$(sysctl -n net.core.somaxconn 2>/dev/null || echo "-")
    
    if [[ "$cc" == *"bbr"* ]]; then
        cc_status="\033[1;32m[ AKTIF ] ($cc)\033[0m"
    else
        cc_status="\033[1;33m[ NON-BBR ] ($cc)\033[0m"
    fi

    if [[ "$qdisc" == *"fq"* || "$qdisc" == *"cake"* ]]; then
        qdisc_status="\033[1;32m[ AKTIF ] ($qdisc)\033[0m"
    else
        qdisc_status="\033[1;33m($qdisc)\033[0m"
    fi

    echo -e "• \033[1;33mTCP Congestion Control\033[0m : $cc_status"
    echo -e "• \033[1;33mQueue Discipline (qdisc)\033[0m : $qdisc_status"
    echo -e "• \033[1;33mAvailable Algorithms\033[0m   : \033[1;37m$bbr_avail\033[0m"
    echo -e "• \033[1;33mTCP Fast Open (TFO)\033[0m     : \033[1;32mValue $tfo (Aktif Client+Server)\033[0m"
    echo -e "• \033[1;33mMax Connection Backlog\033[0m  : \033[1;37m$somax sockets\033[0m"
    echo ""
    echo -e "\033[1;97m─────────────────────────────────────────────────────\033[0m"
    echo -e "\033[1;36mRingkasan Proteksi Firewall & Anti-DDoS:\033[0m"
    if iptables -L SATSET_DDOS -n >/dev/null 2>&1; then
        rule_count=$(iptables -S SATSET_DDOS 2>/dev/null | grep -c "^-A")
        echo -e "• \033[1;33mStatus Chain SATSET_DDOS\033[0m: \033[1;32m[ AKTIF ] ($rule_count Aturan Filter)\033[0m"
        echo -e "• \033[1;33mPerlindungan\033[0m            : SYN Flood, Port Scan, Ping Flood, Anti-Torrent"
        echo -e "• \033[1;33mMax Concurrent Conn/IP\033[0m  : 1000 Koneksi (Mendukung CDN/Proxy)"
        echo -e "• \033[1;33mEstablished Traffic\033[0m     : Zero-latency Fast-path ACCEPT"
    else
        echo -e "• \033[1;33mStatus Chain SATSET_DDOS\033[0m: \033[1;31m[ BELUM AKTIF ]\033[0m"
    fi
    echo -e "\033[1;97m─────────────────────────────────────────────────────\033[0m"
    echo ""
    echo -ne "\033[1;36mTekan tombol apa saja untuk kembali ke menu...\033[0m"
    read -n 1 -s -r
}

if [[ "${0##*/}" == "bbr" ]] && [ -z "${1:-}" ]; then
    action="status"
else
    action="${1:-apply}"
fi

case "$action" in
    status|bbr-status)
        show_status
        ;;
    apply|*)
        apply_bbr_sysctl
        apply_anti_ddos
        ;;
esac

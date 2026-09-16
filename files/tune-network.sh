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
EOF

    # Apply sysctl settings
    sysctl --system >/dev/null 2>&1 || sysctl -p /etc/sysctl.d/99-network-tune.conf >/dev/null 2>&1 || true

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

    # 1. Drop INVALID packets
    iptables -A SATSET_DDOS -m state --state INVALID -j DROP 2>/dev/null || true

    # 2. Drop stealth scan / invalid flags
    iptables -A SATSET_DDOS -p tcp --tcp-flags ALL NONE -j DROP 2>/dev/null || true
    iptables -A SATSET_DDOS -p tcp --tcp-flags ALL ALL -j DROP 2>/dev/null || true
    iptables -A SATSET_DDOS -p tcp --tcp-flags SYN,FIN SYN,FIN -j DROP 2>/dev/null || true
    iptables -A SATSET_DDOS -p tcp --tcp-flags SYN,RST SYN,RST -j DROP 2>/dev/null || true

    # 3. Drop new connection without SYN
    iptables -A SATSET_DDOS -p tcp ! --syn -m state --state NEW -j DROP 2>/dev/null || true

    # 4. Limit TCP SYN flood (50/s with burst 100)
    iptables -A SATSET_DDOS -p tcp --syn -m limit --limit 50/s --limit-burst 100 -j RETURN 2>/dev/null || true
    iptables -A SATSET_DDOS -p tcp --syn -j DROP 2>/dev/null || true

    # 5. Limit concurrent connections per IP (Max 80 simultaneous connections per IP)
    iptables -A SATSET_DDOS -p tcp -m connlimit --connlimit-above 80 --connlimit-mask 32 -j DROP 2>/dev/null || true

    # 6. Limit UDP flood (100/s burst 200)
    iptables -A SATSET_DDOS -p udp -m limit --limit 100/s --limit-burst 200 -j RETURN 2>/dev/null || true

    # 7. Limit ICMP ping flood (2/s burst 5)
    iptables -A SATSET_DDOS -p icmp -m limit --limit 2/s --limit-burst 5 -j RETURN 2>/dev/null || true
    iptables -A SATSET_DDOS -p icmp -j DROP 2>/dev/null || true

    # Insert SATSET_DDOS at top of INPUT chain
    iptables -D INPUT -j SATSET_DDOS 2>/dev/null || true
    iptables -I INPUT 1 -j SATSET_DDOS 2>/dev/null || true

    # 8. Anti-Torrent string inspection in FORWARD and OUTPUT chains
    TORRENT_STRINGS=("BitTorrent" "BitTorrent protocol" "peer_id=" ".torrent" "announce.php?passkey=" "info_hash")
    for chain in FORWARD OUTPUT; do
        for s in "${TORRENT_STRINGS[@]}"; do
            iptables -C "$chain" -m string --string "$s" --algo bm -j DROP 2>/dev/null || \
            iptables -I "$chain" 1 -m string --string "$s" --algo bm -j DROP 2>/dev/null || true
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
    echo -e "\033[1;97m──────────────────────────────────────────\033[0m"
    echo -e "\033[1;92m       STATUS TCP BBR & ANTI-DDOS        \033[0m"
    echo -e "\033[1;97m──────────────────────────────────────────\033[0m"
    echo ""
    cc=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || echo "-")
    qdisc=$(sysctl -n net.core.default_qdisc 2>/dev/null || echo "-")
    bbr_avail=$(sysctl -n net.ipv4.tcp_available_congestion_control 2>/dev/null || echo "-")
    
    echo -e "• \033[1;33mCongestion Control\033[0m  : \033[1;32m$cc\033[0m"
    echo -e "• \033[1;33mQueue Discipline (qdisc)\033[0m: \033[1;32m$qdisc\033[0m"
    echo -e "• \033[1;33mAvailable Algorithms\033[0m  : $bbr_avail"
    echo ""
    echo -e "\033[1;36mRingkasan Aturan Anti-DDoS (iptables):\033[0m"
    if iptables -L SATSET_DDOS -n >/dev/null 2>&1; then
        iptables -L SATSET_DDOS -n -v | head -n 12
    else
        echo "Chain SATSET_DDOS belum aktif."
    fi
    echo ""
    echo -e "\033[1;97m──────────────────────────────────────────\033[0m"
}

action="${1:-apply}"
case "$action" in
    status|bbr-status)
        show_status
        ;;
    apply|*)
        apply_bbr_sysctl
        apply_anti_ddos
        ;;
esac

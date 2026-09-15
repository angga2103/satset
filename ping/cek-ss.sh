#!/bin/bash
clear
LOCK_FILE="/etc/user_locks.db"

function convert_size() {
    local -i bytes=$1
    if [[ $bytes -lt 1024 ]]; then
        echo "${bytes} B"
    elif [[ $bytes -lt 1048576 ]]; then
        echo "$(( (bytes + 1023) / 1024 )) KB"
    elif [[ $bytes -lt 1073741824 ]]; then
        echo "$(( (bytes + 1048575) / 1048576 )) MB"
    else
        echo "$(( (bytes + 1073741823) / 1073741824 )) GB"
    fi
}

function get_isp_info() {
    local ip=$1
    isp_name=$(whois "$ip" 2>/dev/null | grep -Ei 'org-name:|organization:|descr:|netname:' | head -n 1 | awk -F': ' '{print $2}' | sed 's/^[ \t]*//;s/[ \t]*$//')
    if [[ -n "$isp_name" ]]; then
        echo " - ${isp_name}"
    else
        echo ""
    fi
}

clear
> /tmp/other.txt

users=($(grep -E "^#@&" "/etc/xray/config.json" | cut -d ' ' -f 2 | sort -u))

for user in "${users[@]}"; do
    [[ -z "$user" ]] && continue

    > /tmp/ipshadowsocks.txt

    connected_ips=($(grep -w "$user" /var/log/xray/access.log | tail -n 500 | grep -oP '\sfrom\s\K[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}' | sort -u))

    for ip in "${connected_ips[@]}"; do
        if [[ -n "$ip" ]]; then
            echo "$ip" >> /tmp/ipshadowsocks.txt
        fi
    done

    if [[ -s /tmp/ipshadowsocks.txt ]]; then
        limit_quota=$(convert_size "$(cat /etc/shadowsocks/"$user" 2>/dev/null || echo 0)")

        usage_quota=$(convert_size "$(cat "/etc/limit/shadowsocks/${user}" 2>/dev/null || echo 0)")

        active_ip_count=$(wc -l < /tmp/ipshadowsocks.txt)

        limit_ip=$(cat /etc/limit/shadowsocks/ip/"$user" 2>/dev/null || echo "Tidak Dibatasi")

        total_log_count=$(grep -w "$user" /var/log/xray/access.log | tail -n 500 | wc -l)

        lock_status="Aktif"
        if grep -qw "shadowsocks:${user}" "$LOCK_FILE"; then
            lock_status="TERKUNCI"
            lock_time_raw=$(grep -w "shadowsocks:${user}" "$LOCK_FILE" | cut -d ':' -f 3)
            if [[ -n "$lock_time_raw" ]]; then
                current_time=$(date +%s)
                remaining_time=$((900 - (current_time - lock_time_raw))) 

                if [[ "$remaining_time" -gt 0 ]]; then
                    minutes_left=$((remaining_time / 60))
                    seconds_left=$((remaining_time % 60))
                    lock_status="TERKUNCI (${minutes_left}m ${seconds_left}s)"
                else
                    lock_status="TERKUNCI (Menunggu Unban)" 
                fi
            fi
        fi

        printf "User        : %s\n" "${user}"
        printf "Status      : %s\n" "${lock_status}"
        printf "Quota       : %s / %s\n" "${usage_quota}" "${limit_quota}" 
        printf "Batas IP    : %s\n" "${limit_ip}"
        printf "IP Aktif    : %s\n" "${active_ip_count}"
        printf "Total Log   : %s\n" "${total_log_count}"
        
        if [[ "$active_ip_count" -gt 0 ]]; then
            echo "IP ADDRESS  :" 
            while IFS= read -r ip; do
                echo "${ip}"
            done < /tmp/ipshadowsocks.txt
        fi
        echo ""
    fi
done

rm -f /tmp/other.txt /tmp/ipshadowsocks.txt
# > /var/log/xray/access.log
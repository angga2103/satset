#!/usr/bin/env bash
# ==========================================================
# SATSET - SSH Traffic & Quota Limiter (limit-ssh)
# High-performance kernel iptables UID traffic accounting
# ==========================================================
set -u

LOCK_FILE="/etc/user_locks.db"
mkdir -p /etc/ssh /etc/limit/ssh /var/run/satset /run/satset

# 1. Initialize SSH_QUOTA iptables chain if not present
if command -v iptables >/dev/null 2>&1; then
    iptables -N SSH_QUOTA 2>/dev/null || true
    iptables -C OUTPUT -j SSH_QUOTA 2>/dev/null || iptables -I OUTPUT 1 -j SSH_QUOTA 2>/dev/null || true
else
    exit 0
fi

con() {
    local -i bytes=$1
    if [[ $bytes -lt 1024 ]]; then
        echo "${bytes}B"
    elif [[ $bytes -lt 1048576 ]]; then
        echo "$(( (bytes + 1023)/1024 ))KB"
    elif [[ $bytes -lt 1073741824 ]]; then
        echo "$(( (bytes + 1048575)/1048576 ))MB"
    else
        echo "$(( (bytes + 1073741823)/1073741824 ))GB"
    fi
}

send_quota_notif() {
    local user="$1"
    local limit_str="$2"
    local used_str="$3"
    [ ! -f "/etc/bot/.bot.db" ] && return
    local chatid key time url text
    chatid=$(grep -E "^#bot# " "/etc/bot/.bot.db" 2>/dev/null | cut -d ' ' -f 3)
    key=$(grep -E "^#bot# " "/etc/bot/.bot.db" 2>/dev/null | cut -d ' ' -f 2)
    [ -z "$chatid" ] || [ -z "$key" ] && return
    time="10"
    url="https://api.telegram.org/bot$key/sendMessage"
    text="
<code>────────────────────</code>
<b>⚠️ NOTIF KUOTA SSH HABIS ⚠️</b>
<code>────────────────────</code>
<b>Protocol:</b> <code>SSH / WebSocket</code>
<b>User:</b> <code>${user}</code>
<b>Limit Kuota:</b> <code>${limit_str}</code>
<b>Pemakaian:</b> <code>${used_str}</code>
<b>Status:</b> <code>Akun telah dinonaktifkan</code>
<code>────────────────────</code>
<b>🤖 Akun melebihi kuota otomatis dinonaktifkan</b>
<code>────────────────────</code>
"
    curl -s --max-time "$time" -d "chat_id=$chatid&disable_web_page_preview=1&text=$text&parse_mode=html" "$url" >/dev/null 2>&1 || true
}

# 2. Iterate registered SSH users
if [ -f /etc/ssh/.ssh.db ]; then
    iptables_out=$(iptables -nvx -L SSH_QUOTA 2>/dev/null || true)

    while read -r tag user exp pass iplimit quota rest; do
        if [[ "$tag" == "###" ]]; then
            : # standard format: tag user exp pass iplimit quota
        elif [[ "$tag" == "#ssh#" ]]; then
            # legacy format: #ssh# user pass quota iplimit exp
            tmp_pass="$exp"
            tmp_quota="$pass"
            tmp_iplimit="$iplimit"
            tmp_exp="$quota"
            pass="$tmp_pass"
            quota="$tmp_quota"
            iplimit="$tmp_iplimit"
            exp="$tmp_exp"
        else
            continue
        fi
        [ -z "$user" ] && continue
        
        uid=$(id -u "$user" 2>/dev/null || echo "")
        [[ -z "$uid" || "$uid" -lt 1000 ]] && continue

        # Ensure iptables rule exists for this UID
        if ! echo "$iptables_out" | grep -q "owner UID match $uid\b"; then
            iptables -A SSH_QUOTA -m owner --uid-owner "$uid" -j RETURN 2>/dev/null || true
            # Refresh output
            iptables_out=$(iptables -nvx -L SSH_QUOTA 2>/dev/null || true)
        fi

        # Extract current bytes from iptables
        cur_bytes=$(echo "$iptables_out" | awk -v u="$uid" '$0 ~ "owner UID match " u {print $2}' | head -n1)
        [ -z "$cur_bytes" ] && cur_bytes=0

        # Read previous snapshot
        prev_file="/var/run/satset/ssh_bytes_${user}"
        prev_bytes=0
        [ -f "$prev_file" ] && prev_bytes=$(cat "$prev_file" 2>/dev/null || echo 0)

        # Calculate delta
        if [ "$cur_bytes" -ge "$prev_bytes" ]; then
            delta=$((cur_bytes - prev_bytes))
        else
            delta=$cur_bytes
        fi
        echo "$cur_bytes" > "$prev_file"

        # Accumulate usage in /etc/limit/ssh/$user
        used_file="/etc/limit/ssh/${user}"
        used_bytes=0
        [ -f "$used_file" ] && used_bytes=$(cat "$used_file" 2>/dev/null || echo 0)
        [ -z "$used_bytes" ] && used_bytes=0

        if [ "$delta" -gt 0 ]; then
            used_bytes=$((used_bytes + delta))
            echo "$used_bytes" > "$used_file"
        fi

        # Read quota limit (bytes)
        quota_file="/etc/ssh/${user}"
        quota_limit=0
        if [ -f "$quota_file" ]; then
            quota_limit=$(cat "$quota_file" 2>/dev/null || echo 0)
        elif [[ -n "${quota:-}" && "$quota" =~ ^[0-9]+$ && "$quota" -gt 0 ]]; then
            quota_limit=$((quota * 1024 * 1024 * 1024))
            echo "$quota_limit" > "$quota_file"
        fi

        # Enforcement: lock if quota exceeded, unlock if under quota
        if [ "$quota_limit" -gt 0 ] && [ "$used_bytes" -ge "$quota_limit" ]; then
            if ! grep -qw "ssh:${user}" "$LOCK_FILE" 2>/dev/null; then
                usermod -L "$user" 2>/dev/null || true
                pkill -u "$user" 2>/dev/null || true
                echo "ssh:${user}:$(date +%s):525600:quota_exceeded" >> "$LOCK_FILE"
                send_quota_notif "$user" "$(con "$quota_limit")" "$(con "$used_bytes")"
            fi
        else
            # If locked for quota_exceeded but now under quota or unli (e.g. admin renewed/reset)
            if grep -q "ssh:${user}:.*:quota_exceeded" "$LOCK_FILE" 2>/dev/null; then
                usermod -U "$user" 2>/dev/null || true
                sed -i "/ssh:${user}:.*:quota_exceeded/d" "$LOCK_FILE" 2>/dev/null || true
            fi
        fi
    done < /etc/ssh/.ssh.db
fi

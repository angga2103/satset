#!/bin/bash

if [[ $EUID -ne 0 ]]; then
    echo "Skrip ini harus dijalankan sebagai root."
    exit 1
fi

install_services() {
    local REPO="https://raw.githubusercontent.com/angga2103/satset/main/files/"
    local LIMIT_IP_SERVICES=("limiter-vm" "limiter-vl" "limiter-trj" "limiter-shd")
    local LIMIT_IP_REMOTE_FILES=("lite-vm" "lite-vl" "lite-trj" "lite-shd")
    local LIMIT_QUOTA_SERVICES=("limitvmess" "limitvless" "limittrojan" "limitshadowsocks")
    local LIMIT_QUOTA_REMOTE_FILES=("vmess" "vless" "trojan" "shadowsocks")
    local ALL_SERVICES=("${LIMIT_IP_SERVICES[@]}" "${LIMIT_QUOTA_SERVICES[@]}")

    echo "Memulai instalasi layanan systemd..."

    echo "1. Menghapus layanan lama dan file terkait..."
    for service in "${ALL_SERVICES[@]}"; do
        systemctl disable --now "${service}.timer" &>/dev/null
        systemctl disable --now "${service}.service" &>/dev/null
        rm -f "/etc/systemd/system/${service}.service"
        rm -f "/etc/systemd/system/${service}.timer"
        echo "- ${service} dihapus."
    done

    rm -f "/usr/local/bin/"{lite-vm,lite-vl,lite-trj,lite-shd} &>/dev/null
    rm -f "/etc/xray/limit."{vmess,vless,trojan,shadowsocks} &>/dev/null
    echo "- File biner lama dihapus."

    echo "2. Menginstal skrip dan membuat layanan Limit IP..."
    for i in "${!LIMIT_IP_SERVICES[@]}"; do
        local service="${LIMIT_IP_SERVICES[$i]}"
        local remote_file="${LIMIT_IP_REMOTE_FILES[$i]}"
        local binary_path="/usr/local/bin/${remote_file}"

        echo "- Mengunduh skrip ${remote_file}..."
        wget -q -O "${binary_path}" "${REPO}/${remote_file}" || {
            echo "Gagal mengunduh ${remote_file}. Lanjut ke layanan berikutnya."
            continue
        }
        chmod +x "${binary_path}"

        cat > "/etc/systemd/system/${service}.service" << EOF
[Unit]
Description=${service} Service
After=network.target

[Service]
Type=oneshot
ExecStart=${binary_path}

[Install]
WantedBy=multi-user.target
EOF

        cat > "/etc/systemd/system/${service}.timer" << EOF
[Unit]
Description=Run ${service} every minute

[Timer]
OnCalendar=minutely
Persistent=true
Unit=${service}.service

[Install]
WantedBy=timers.target
EOF
        echo "- Layanan ${service} dibuat."
    done

    echo "3. Menginstal skrip dan membuat layanan Limit Kuota..."
    mkdir -p /etc/xray/
    for i in "${!LIMIT_QUOTA_SERVICES[@]}"; do
        local service="${LIMIT_QUOTA_SERVICES[$i]}"
        local remote_file="${LIMIT_QUOTA_REMOTE_FILES[$i]}"
        local binary_path="/etc/xray/limit.${remote_file}"

        echo "- Mengunduh skrip limit.${remote_file}..."
        wget -q -O "${binary_path}" "${REPO}/${remote_file}" || {
            echo "Gagal mengunduh ${remote_file}. Lanjut ke layanan berikutnya."
            continue
        }
        chmod +x "${binary_path}"

        cat > "/etc/systemd/system/${service}.service" << EOF
[Unit]
Description=${service} Service
After=network.target

[Service]
Type=oneshot
ExecStart=${binary_path}

[Install]
WantedBy=multi-user.target
EOF

        cat > "/etc/systemd/system/${service}.timer" << EOF
[Unit]
Description=Run ${service} every minute

[Timer]
OnCalendar=minutely
Persistent=true
Unit=${service}.service

[Install]
WantedBy=timers.target
EOF
        echo "- Layanan ${service} dibuat."
    done

    echo "4. Memuat ulang systemd dan mengaktifkan semua timer..."
    systemctl daemon-reload
    for service in "${ALL_SERVICES[@]}"; do
        systemctl enable --now "${service}.timer" &>/dev/null
        echo "- ${service}.timer diaktifkan."
    done

    echo "Semua layanan berhasil dipasang dan diaktifkan."
}

install_services

rm -f "$0"

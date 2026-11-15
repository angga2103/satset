#!/usr/bin/env bash
# ==============================================================================
# SATSET Test Suite: OS Detection & Architecture Matrix Validation
# ==============================================================================
set -euo pipefail

PASS=0
FAIL=0

echo "=== [2/7] Testing OS Detection & Compatibility Matrix ==="

test_os() {
    local os_id="$1"
    local ver_id="$2"
    local codename="$3"
    local expected_dns="$4"

    local selected_dns=""
    if [ "$os_id" = "ubuntu" ] && [ "$ver_id" = "24.04" ]; then
        selected_dns="bind9-dnsutils"
    elif [ "$os_id" = "debian" ] && [ "$ver_id" = "12" ]; then
        selected_dns="bind9-dnsutils"
    else
        selected_dns="dnsutils"
    fi

    if [ "$selected_dns" = "$expected_dns" ]; then
        echo "  [PASS] $os_id $ver_id ($codename) -> DNS package correctly mapped to $selected_dns"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $os_id $ver_id ($codename) -> Expected $expected_dns but got $selected_dns"
        FAIL=$((FAIL + 1))
    fi
}

test_arch() {
    local arch="$1"
    local expected_xray="$2"
    local actual_xray=""

    case "$arch" in
        x86_64|amd64) actual_xray="64" ;;
        aarch64|arm64) actual_xray="arm64-v8a" ;;
        armv7l|armv7) actual_xray="arm32-v7a" ;;
        *) actual_xray="unsupported" ;;
    esac

    if [ "$actual_xray" = "$expected_xray" ]; then
        echo "  [PASS] Architecture $arch mapped to Xray binary: Xray-linux-${actual_xray}.zip"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] Architecture $arch expected $expected_xray, got $actual_xray"
        FAIL=$((FAIL + 1))
    fi
}

# Test Operating Systems
test_os "ubuntu" "20.04" "focal" "dnsutils"
test_os "ubuntu" "22.04" "jammy" "dnsutils"
test_os "ubuntu" "24.04" "noble" "bind9-dnsutils"
test_os "debian" "11" "bullseye" "dnsutils"
test_os "debian" "12" "bookworm" "bind9-dnsutils"

# Test Architectures
test_arch "x86_64" "64"
test_arch "amd64" "64"
test_arch "aarch64" "arm64-v8a"
test_arch "arm64" "arm64-v8a"

echo ""
echo "Summary: $PASS Passed, $FAIL Failed"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi

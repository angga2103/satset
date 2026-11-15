#!/usr/bin/env bash
# ==============================================================================
# SATSET Test Suite: Firewall & IPv6 Netfilter Persistence Logic Test
# ==============================================================================
set -euo pipefail

PASS=0
FAIL=0

echo "=== [7/7] Testing Firewall & IPv6 Netfilter Logic ==="

# 1. Test SSH port protection rule
test_ssh_rule() {
    local script="$1"
    if grep -q "iptables -I INPUT -p tcp --dport 22 -j ACCEPT" "$script"; then
        echo "  [PASS] SSH Port 22 protection rule present in $(basename "$script")"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] Missing SSH protection rule in $(basename "$script")"
        FAIL=$((FAIL + 1))
    fi
}

# 2. Test dynamic IPv6 netfilter check
test_ipv6_logic() {
    local script="$1"
    if grep -q "disable_ipv6.*ip6tables" "$script" || grep -q "disable_ipv6.*rules.v6" "$script" || grep -q "25-ip6tables" "$script"; then
        echo "  [PASS] Dynamic IPv6 netfilter handling present in $(basename "$script")"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] Missing dynamic IPv6 handling in $(basename "$script")"
        FAIL=$((FAIL + 1))
    fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

test_ssh_rule "$SCRIPT_DIR/setup.sh"
test_ssh_rule "$SCRIPT_DIR/update.sh"
test_ipv6_logic "$SCRIPT_DIR/setup.sh"
test_ipv6_logic "$SCRIPT_DIR/update.sh"

echo ""
echo "Summary: $PASS Passed, $FAIL Failed"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi

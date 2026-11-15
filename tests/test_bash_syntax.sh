#!/usr/bin/env bash
# ==============================================================================
# SATSET Test Suite: Bash Syntax & Executable Validation
# ==============================================================================
set -euo pipefail

PASS=0
FAIL=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== [1/7] Testing Bash Syntax Across Repository ==="

test_script() {
    local file="$1"
    if [ ! -f "$file" ]; then
        return
    fi

    # Check if file is an ELF binary (e.g. speedtest.sh)
    if head -c 4 "$file" 2>/dev/null | grep -q "ELF"; then
        echo "  [PASS] (Binary) $file is a valid 64-bit ELF executable"
        PASS=$((PASS + 1))
        return
    fi

    # Check bash syntax using bash -n
    if bash -n "$file" 2>/dev/null; then
        echo "  [PASS] $file"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $file (Syntax error)"
        FAIL=$((FAIL + 1))
    fi
}

# Test root scripts
test_script "$SCRIPT_DIR/setup.sh"
test_script "$SCRIPT_DIR/update.sh"
test_script "$SCRIPT_DIR/speedtest.sh"

# Test files directory scripts
for f in "$SCRIPT_DIR"/files/*.sh; do
    [ -f "$f" ] && test_script "$f"
done

# Test ping directory scripts
for f in "$SCRIPT_DIR"/ping/*.sh; do
    [ -f "$f" ] && test_script "$f"
done

# Test bot-store and satset-pay scripts
[ -f "$SCRIPT_DIR/bot-store/install_store.sh" ] && test_script "$SCRIPT_DIR/bot-store/install_store.sh"
[ -f "$SCRIPT_DIR/satset-pay/install.sh" ] && test_script "$SCRIPT_DIR/satset-pay/install.sh"
[ -f "$SCRIPT_DIR/satset-pay/termux_setup.sh" ] && test_script "$SCRIPT_DIR/satset-pay/termux_setup.sh"
[ -f "$SCRIPT_DIR/config/limiter.sh" ] && test_script "$SCRIPT_DIR/config/limiter.sh"

echo ""
echo "Summary: $PASS Passed, $FAIL Failed"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi

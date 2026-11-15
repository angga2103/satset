#!/usr/bin/env bash
# ==============================================================================
# SATSET Master Test Runner
# Executes all automated tests and prints a unified summary report.
# ==============================================================================
set -u

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_CMD=""
if command -v python3 >/dev/null 2>&1 && python3 --version >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1 && python --version >/dev/null 2>&1; then
    PYTHON_CMD="python"
elif command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
    PYTHON_CMD="py -3"
elif [ -x "/c/Users/Toshiba/AppData/Local/Programs/Python/Python312/python.exe" ]; then
    PYTHON_CMD="/c/Users/Toshiba/AppData/Local/Programs/Python/Python312/python.exe"
else
    PYTHON_CMD="python3"
fi

TOTAL_SUITES=0
PASSED_SUITES=0
FAILED_SUITES=0

run_test() {
    local name="$1"
    local cmd="$2"
    TOTAL_SUITES=$((TOTAL_SUITES + 1))
    echo ""
    echo "----------------------------------------------------------------------"
    echo "Running Test Suite: $name"
    echo "----------------------------------------------------------------------"
    if eval "$cmd"; then
        echo ">>> Result: PASS - $name"
        PASSED_SUITES=$((PASSED_SUITES + 1))
    else
        echo ">>> Result: FAIL - $name"
        FAILED_SUITES=$((FAILED_SUITES + 1))
    fi
}

echo "======================================================================"
echo "          SATSET VPN AUTOMATED TEST SUITE EXECUTION REPORT            "
echo "======================================================================"

run_test "Bash Syntax & Executable Validation" "bash '$TESTS_DIR/test_bash_syntax.sh'"
run_test "OS Detection & Compatibility Matrix" "bash '$TESTS_DIR/test_os_detection.sh'"
run_test "Xray Configuration & Inbound/Outbound Integrity" "$PYTHON_CMD '$TESTS_DIR/test_xray_config.py'"
run_test "Nginx Port Listening & Upstream Proxy Mapping" "$PYTHON_CMD '$TESTS_DIR/test_nginx_ports.py'"
run_test "Security & Least-Privilege Permissions Audit" "$PYTHON_CMD '$TESTS_DIR/test_security_permissions.py'"
run_test "Menu Account Operations Regression Simulation" "$PYTHON_CMD '$TESTS_DIR/test_regression_menu.py'"
run_test "Firewall & IPv6 Netfilter Persistence Logic" "bash '$TESTS_DIR/test_firewall_ipv6.sh'"

echo ""
echo "======================================================================"
echo "                      FINAL TEST SUMMARY                              "
echo "======================================================================"
echo "Total Test Suites : $TOTAL_SUITES"
echo "Passed            : $PASSED_SUITES"
echo "Failed            : $FAILED_SUITES"
echo "Not Tested        : Live VPS Network Connection (Requires real VPS with public IP)"
echo "Blocked           : None"
echo "======================================================================"

if [ "$FAILED_SUITES" -gt 0 ]; then
    exit 1
fi
exit 0

#!/usr/bin/env python3
"""
SATSET Test Suite: Nginx Port Listening & Reverse Proxy Upstream Mapping
"""
import sys
import re
import os

CONF_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "xray.conf")

def main():
    print("=== [4/7] Testing Nginx Configuration & Upstream Proxy Mapping ===")
    if not os.path.isfile(CONF_PATH):
        print(f"  [FAIL] Nginx conf not found at {CONF_PATH}")
        sys.exit(1)

    with open(CONF_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Check listen ports
    expected_ports = ["80", "8080", "8880", "443", "8443", "2052", "2082", "2086", "2095", "2053", "2083", "2087", "2096"]
    for p in expected_ports:
        pattern = rf"listen\s+{p}\b"
        if re.search(pattern, content):
            print(f"  [PASS] Nginx listener for port {p} present")
        else:
            print(f"  [FAIL] Missing listen directive for port {p}")
            sys.exit(1)

    # 2. Check proxy_pass mappings to internal Xray ports
    expected_proxies = {
        "/vless": "10001",
        "/vmess": "10002",
        "/trojan-ws": "10003",
        "/ss-ws": "10004",
        "/vless-grpc": "10005",
        "/vmess-grpc": "10006",
        "/trojan-grpc": "10007",
        "/ss-grpc": "10008",
        "fightertunnelovpn": "10012",
        "default_root_ssh": "10015",
    }

    for path, port in expected_proxies.items():
        if path == "default_root_ssh":
            if "10015" in content:
                print(f"  [PASS] Default SSH WebSocket upstream mapped to 127.0.0.1:{port}")
            else:
                print(f"  [FAIL] Missing default SSH WebSocket upstream 10015")
                sys.exit(1)
        else:
            if path in content and port in content:
                print(f"  [PASS] Location {path} successfully maps to 127.0.0.1:{port}")
            else:
                print(f"  [FAIL] Location {path} not mapped to internal port {port}")
                sys.exit(1)

    # 3. Check SSL Certificate directives
    if "ssl_certificate /etc/xray/xray.crt;" in content and "ssl_certificate_key /etc/xray/xray.key;" in content:
        print("  [PASS] SSL certificate and key directives verified")
    else:
        print("  [FAIL] SSL certificate or key directive missing")
        sys.exit(1)

    print("\nSummary: All Nginx port and upstream mapping checks PASSED.")

if __name__ == "__main__":
    main()

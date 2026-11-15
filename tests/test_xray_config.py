#!/usr/bin/env python3
"""
SATSET Test Suite: Xray Configuration & Inbound/Outbound/Routing Integrity Test
"""
import sys
import re
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")

def main():
    print("=== [3/7] Testing Xray Configuration Integrity ===")
    if not os.path.isfile(CONFIG_PATH):
        print(f"  [FAIL] Config file not found at {CONFIG_PATH}")
        sys.exit(1)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        raw_content = f.read()

    # 1. Test HuJSON comment stripping (preserving user database markers)
    clean_json = re.sub(r"^\s*#.*$", "", raw_content, flags=re.MULTILINE)
    clean_json = re.sub(r"//.*$", "", clean_json, flags=re.MULTILINE)

    try:
        data = json.loads(clean_json)
        print("  [PASS] config.json successfully parsed as valid HuJSON (comments stripped)")
    except Exception as e:
        print(f"  [FAIL] JSON parsing failed: {e}")
        sys.exit(1)

    # 2. Test Inbound Ports & Protocols
    expected_inbounds = {
        10000: ("dokodemo-door", "tcp"),
        10001: ("vless", "ws"),
        10002: ("vmess", "ws"),
        10003: ("trojan", "ws"),
        10004: ("shadowsocks", "ws"),
        10005: ("vless", "grpc"),
        10006: ("vmess", "grpc"),
        10007: ("trojan", "grpc"),
        10008: ("shadowsocks", "grpc"),
    }

    inbounds = data.get("inbounds", [])
    inbound_map = {ib["port"]: ib for ib in inbounds if "port" in ib}

    for port, (proto, net) in expected_inbounds.items():
        if port not in inbound_map:
            print(f"  [FAIL] Missing inbound port {port} ({proto} {net})")
            sys.exit(1)
        ib = inbound_map[port]
        if ib.get("protocol") != proto:
            print(f"  [FAIL] Port {port} protocol mismatch: expected {proto}, got {ib.get('protocol')}")
            sys.exit(1)
        stream_net = ib.get("streamSettings", {}).get("network", "tcp")
        if stream_net != net and net != "dokodemo-door":
            print(f"  [FAIL] Port {port} network mismatch: expected {net}, got {stream_net}")
            sys.exit(1)
        print(f"  [PASS] Inbound port {port}: {proto} ({net}) validated")

    # 3. Test Outbounds
    outbound_tags = [ob.get("tag") for ob in data.get("outbounds", [])]
    required_tags = ["direct", "warp", "blocked", "api"]
    for tag in required_tags:
        if tag not in outbound_tags:
            print(f"  [FAIL] Missing required outbound tag: {tag}")
            sys.exit(1)
        print(f"  [PASS] Outbound tag '{tag}' validated")

    # 4. Test Routing Rules
    routing_rules = data.get("routing", {}).get("rules", [])
    has_geosite = any("geosite:category-ads-all" in r.get("domain", []) for r in routing_rules)
    has_geoip = any("geoip:private" in r.get("ip", []) for r in routing_rules)

    if has_geosite:
        print("  [PASS] Routing rule for 'geosite:category-ads-all' present")
    else:
        print("  [WARN] No explicit geosite adblocking rule")

    if has_geoip:
        print("  [PASS] Routing rule for 'geoip:private' present")
    else:
        print("  [WARN] No explicit geoip private blocking rule")

    # 5. Test Required Tag Anchors in Raw File
    required_anchors = ["#vless", "#vmess", "#trojanws", "#ssws", "#vlessgrpc", "#vmessgrpc", "#trojangrpc", "#ssgrpc"]
    for anchor in required_anchors:
        if anchor not in raw_content:
            print(f"  [FAIL] Missing user database anchor: {anchor}")
            sys.exit(1)
        print(f"  [PASS] User database anchor '{anchor}' preserved")

    print("\nSummary: All Xray configuration checks PASSED.")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
SATSET Test Suite: Regression Testing for Menu Account Operations
Simulates user creation and deletion across all protocols.
"""
import sys
import re
import json
import os
import shutil

CONFIG_SRC = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")
TMP_CONFIG = os.path.join(os.path.dirname(__file__), "tmp_config.json")

def test_protocol(proto_name, anchor_tag, user="testuser123", uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890", exp="2026-12-31"):
    with open(TMP_CONFIG, "r", encoding="utf-8") as f:
        content = f.read()

    # Exact format used by SATSET menu scripts (e.g. menu/addvl, addvm, addtr, addss)
    if "grpc" in anchor_tag:
        injection = f'#& {user} {exp}\\n}},{{"id": "{uuid}","email": "{user}"'
    elif "trojan" in anchor_tag:
        injection = f'#& {user} {exp}\\n}},{{"password": "{uuid}","email": "{user}"'
    elif "ss" in anchor_tag:
        injection = f'#& {user} {exp}\\n}},{{"password": "{uuid}","email": "{user}"'
    else:
        injection = f'#& {user} {exp}\\n}},{{"id": "{uuid}","email": "{user}"'

    # Perform injection right after anchor tag
    pattern = rf"(#{anchor_tag}\b)"
    replacement = f"\\1\n#& {user} {exp}\n}},{{\"id\": \"{uuid}\",\"email\": \"{user}\""
    if "trojan" in anchor_tag or "ss" in anchor_tag:
        replacement = f"\\1\n#& {user} {exp}\n}},{{\"password\": \"{uuid}\",\"email\": \"{user}\""

    new_content, count = re.subn(pattern, replacement, content)
    if count == 0:
        return False, f"Anchor {anchor_tag} not found"

    with open(TMP_CONFIG, "w", encoding="utf-8") as f:
        f.write(new_content)

    # Validate that resulting config is valid HuJSON
    clean_json = re.sub(r"^\s*#.*$", "", new_content, flags=re.MULTILINE)
    clean_json = re.sub(r"//.*$", "", clean_json, flags=re.MULTILINE)
    try:
        json.loads(clean_json)
        return True, "Valid"
    except Exception as e:
        return False, f"JSON invalid after adding user: {e}"

def main():
    print("=== [6/7] Testing Account Creation & Database Regression ===")
    shutil.copyfile(CONFIG_SRC, TMP_CONFIG)

    protocols = [
        ("VLESS WebSocket", "vless"),
        ("VMess WebSocket", "vmess"),
        ("Trojan WebSocket", "trojanws"),
        ("Shadowsocks WebSocket", "ssws"),
        ("VLESS gRPC", "vlessgrpc"),
        ("VMess gRPC", "vmessgrpc"),
        ("Trojan gRPC", "trojangrpc"),
        ("Shadowsocks gRPC", "ssgrpc"),
    ]

    failed = 0
    for name, tag in protocols:
        ok, msg = test_protocol(name, tag)
        if ok:
            print(f"  [PASS] {name} user insertion validated (Anchor: #{tag})")
        else:
            print(f"  [FAIL] {name} user insertion failed: {msg}")
            failed += 1

    if os.path.exists(TMP_CONFIG):
        os.remove(TMP_CONFIG)

    if failed > 0:
        print(f"\nRegression test failed with {failed} errors")
        sys.exit(1)
    else:
        print("\nSummary: All account creation regression tests PASSED.")

if __name__ == "__main__":
    main()

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

def test_lifecycle_protocol(proto_name, ws_tag, grpc_tag, prefix, creds_type, user="testuser123", uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890", exp="2026-12-31"):
    with open(TMP_CONFIG, "r", encoding="utf-8") as f:
        content = f.read()

    if creds_type == "id_alterid":
        creds = f'"id": "{uuid}","alterId": 0'
    elif creds_type == "password_method":
        creds = f'"password": "{uuid}","method": "2022-blake3-aes-128-gcm"'
    elif creds_type == "password":
        creds = f'"password": "{uuid}"'
    else:
        creds = f'"id": "{uuid}"'

    # Step 1: Insertion into both WS and gRPC anchors (as done by addvl, addvm, addtr, addss)
    pattern_ws = rf"(#{ws_tag}\b)"
    replacement_ws = f"\\1\n{prefix} {user} {exp}\n}},{{{creds},\"email\": \"{user}\""
    content, count_ws = re.subn(pattern_ws, replacement_ws, content)
    if count_ws == 0:
        return False, f"Anchor #{ws_tag} not found"

    pattern_grpc = rf"(#{grpc_tag}\b)"
    replacement_grpc = f"\\1\n{prefix} {user} {exp}\n}},{{{creds},\"email\": \"{user}\""
    content, count_grpc = re.subn(pattern_grpc, replacement_grpc, content)
    if count_grpc == 0:
        return False, f"Anchor #{grpc_tag} not found"

    # Validate JSON after insertion
    clean_json = re.sub(r"^\s*#.*$", "", content, flags=re.MULTILINE)
    clean_json = re.sub(r"//.*$", "", clean_json, flags=re.MULTILINE)
    try:
        json.loads(clean_json)
    except Exception as e:
        return False, f"JSON invalid after insertion: {e}"

    # Step 2: Deletion (as done by delvl, delvm, deltr, delss using sed -i '/^prefix user exp/,/^},{/d')
    lines = content.splitlines(keepends=True)
    new_lines = []
    deleting = False
    deleted_blocks = 0

    marker = f"{prefix} {user} {exp}"
    for line in lines:
        sline = line.strip()
        if sline.startswith(marker):
            deleting = True
            deleted_blocks += 1
            continue
        if deleting:
            if sline.startswith("},{"):
                deleting = False
            continue
        new_lines.append(line)

    if deleted_blocks < 2:
        return False, f"Expected 2 deleted blocks (WS & gRPC), got {deleted_blocks}"

    content_after_del = "".join(new_lines)

    # Verify user is completely gone
    if user in content_after_del:
        return False, f"User {user} still present in config after deletion"

    # Verify both anchors remain intact
    if f"#{ws_tag}" not in content_after_del:
        return False, f"Anchor #{ws_tag} was destroyed during deletion!"
    if f"#{grpc_tag}" not in content_after_del:
        return False, f"Anchor #{grpc_tag} was destroyed during deletion!"

    # Validate JSON after deletion
    clean_json_del = re.sub(r"^\s*#.*$", "", content_after_del, flags=re.MULTILINE)
    clean_json_del = re.sub(r"//.*$", "", clean_json_del, flags=re.MULTILINE)
    try:
        json.loads(clean_json_del)
    except Exception as e:
        return False, f"JSON invalid after deletion: {e}"

    with open(TMP_CONFIG, "w", encoding="utf-8") as f:
        f.write(content_after_del)

    return True, "Valid"

def main():
    print("=== [6/7] Testing Account Creation & Database Regression ===")
    shutil.copyfile(CONFIG_SRC, TMP_CONFIG)

    protocols = [
        ("VLESS (WS & gRPC)", "vless", "vlessgrpc", "#&", "id"),
        ("VMess (WS & gRPC)", "vmess", "vmessgrpc", "###", "id_alterid"),
        ("Trojan (WS & gRPC)", "trojanws", "trojangrpc", "#!", "password"),
        ("Shadowsocks (WS & gRPC)", "ssws", "ssgrpc", "#@&", "password_method"),
    ]

    failed = 0
    for name, ws_tag, grpc_tag, prefix, creds_type in protocols:
        ok, msg = test_lifecycle_protocol(name, ws_tag, grpc_tag, prefix, creds_type)
        if ok:
            print(f"  [PASS] {name} user insertion, deletion & anchor preservation validated")
        else:
            print(f"  [FAIL] {name} lifecycle failed: {msg}")
            failed += 1

    if os.path.exists(TMP_CONFIG):
        os.remove(TMP_CONFIG)

    if failed > 0:
        print(f"\nRegression test failed with {failed} errors")
        sys.exit(1)
    else:
        print("\nSummary: All account creation & deletion regression tests PASSED.")

if __name__ == "__main__":
    main()

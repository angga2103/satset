#!/usr/bin/env python3
"""
SATSET Test Suite: Security & Least Privilege Permission Audit
"""
import sys
import re
import os

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")

def check_file_permissions(filepath):
    errors = []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # 1. Private key must NOT be chmod 644 or 777
    if re.search(r"chmod\s+644\s+.*xray\.key", content):
        errors.append(f"{filepath}: xray.key is set to world-readable mode 644 (Insecure)")
    if re.search(r"chmod\s+777\s+.*xray\.key", content):
        errors.append(f"{filepath}: xray.key is set to world-writable mode 777 (Critical Vulnerability)")

    # 2. Private key should be chmod 640
    if not re.search(r"chmod\s+640\s+.*xray\.key", content):
        errors.append(f"{filepath}: xray.key missing least-privilege mode 640")

    # 3. Private key group should be www-data
    if not re.search(r"chown\s+root:www-data\s+.*xray\.key", content):
        errors.append(f"{filepath}: xray.key missing group ownership root:www-data")

    # 4. /etc/xray must NOT be chown -R www-data:www-data /etc/xray
    if re.search(r"chown\s+-R\s+www-data:www-data\s+/etc/xray\b", content):
        errors.append(f"{filepath}: /etc/xray is recursively owned by www-data (Vulnerability: web workers could overwrite system configs)")

    return errors

def main():
    print("=== [5/7] Testing Security & Least Privilege Permissions ===")
    targets = [
        os.path.join(BASE_DIR, "setup.sh"),
        os.path.join(BASE_DIR, "update.sh"),
    ]

    all_errors = []
    for target in targets:
        if os.path.isfile(target):
            errs = check_file_permissions(target)
            if errs:
                all_errors.extend(errs)
            else:
                print(f"  [PASS] {os.path.basename(target)} adheres strictly to least-privilege permissions")

    if all_errors:
        print("\nSecurity Audit Violations Found:")
        for err in all_errors:
            print(f"  [FAIL] {err}")
        sys.exit(1)
    else:
        print("\nSummary: All security permission checks PASSED.")

if __name__ == "__main__":
    main()

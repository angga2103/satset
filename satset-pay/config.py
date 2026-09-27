#!/usr/bin/env python3
"""
SATSET-PAY: Configuration Module
Handles environment variables, default ports, database paths, and secrets.
"""

import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_CONFIG_DIR = "/etc/satset"

def get_config_dir():
    if os.path.exists(SYSTEM_CONFIG_DIR) or os.name != "nt":
        os.makedirs(SYSTEM_CONFIG_DIR, exist_ok=True)
        return SYSTEM_CONFIG_DIR
    local_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(local_dir, exist_ok=True)
    return local_dir

CONFIG_DIR = get_config_dir()
DB_FILE = os.path.join(CONFIG_DIR, "satset-pay.db")
SECRET_KEY_FILE = os.path.join(CONFIG_DIR, "pay-secret.key")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "pay-settings.json")

def get_or_create_secret_key() -> str:
    if os.path.exists(SECRET_KEY_FILE):
        try:
            with open(SECRET_KEY_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
                if key and len(key) >= 16:
                    return key
        except Exception:
            pass
    new_key = secrets.token_hex(32)
    try:
        with open(SECRET_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(new_key + "\n")
        if os.name != "nt":
            os.chmod(SECRET_KEY_FILE, 0o600)
    except Exception:
        pass
    return new_key

SERVER_HOST = os.environ.get("SATSET_PAY_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SATSET_PAY_PORT", 8088))
SECRET_KEY = get_or_create_secret_key()
DEFAULT_ADMIN_USER = os.environ.get("SATSET_PAY_ADMIN", "admin")
DEFAULT_ADMIN_PASS = os.environ.get("SATSET_PAY_PASS", "admin123")

# Invoice Settings
INVOICE_TIMEOUT_MINUTES = 10
UNIQUE_CODE_MIN = 1
UNIQUE_CODE_MAX = 499

VERSION = "1.0.0"

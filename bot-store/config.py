import os
import json

ENV_FILE = "/etc/satset/bot.env"
LOCAL_ENV = os.path.join(os.path.dirname(__file__), "bot.env")

DEFAULT_CONFIG = {
    "BOT_TOKEN": "",
    "ADMIN_ID": "",
    "PAKASIR_PROJECT_SLUG": "",
    "PAKASIR_API_KEY": "",
    "PRICE_MONTHLY": 8000,
    "PRICE_PAYG_DAILY": 300,
    "PRICE_PAYG_10GB": 1000,
    "DEFAULT_IP_LIMIT": 1,
    "DEFAULT_QUOTA_GB": 350,  # 350 GB (0 = unlimited)
    "SUSPEND_DURATION_MINUTES": 10,  # Auto-suspend duration in minutes
    "AUTO_SUSPEND_ENABLED": 1,  # 1 = auto suspend on IP violation, 0 = notify only
    "NOTIFY_VIOLATIONS": 1,  # 1 = send Telegram alerts on violation
    "CURRENCY": "Rp"
}

def get_env_path():
    if os.path.exists("/etc/satset"):
        return ENV_FILE
    return LOCAL_ENV

def load_config():
    config = DEFAULT_CONFIG.copy()
    env_path = get_env_path()
    
    # 1. Fallback to OS environment if present
    for k in config:
        if k in os.environ:
            val = os.environ[k]
            if isinstance(config[k], int):
                try:
                    config[k] = int(val)
                except ValueError:
                    pass
            else:
                config[k] = val

    # 2. Persisted file /etc/satset/bot.env takes HIGHEST precedence
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        if "#" in v:
                            v = v.split("#", 1)[0]
                        v = v.strip().strip('"').strip("'")
                        if k in config:
                            if isinstance(config[k], int):
                                try:
                                    config[k] = int(v)
                                except ValueError:
                                    pass
                            else:
                                config[k] = v
                        else:
                            config[k] = v
        except Exception as e:
            print(f"[WARN] Failed to read {env_path}: {e}")

    return config

def save_config(new_data: dict):
    env_path = get_env_path()
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    
    # Update file in-place to preserve comments and layout
    existing_lines = []
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                existing_lines = f.readlines()
        except Exception as e:
            print(f"[WARN] Failed to read existing {env_path}: {e}")

    written_keys = set()
    new_lines = []
    for line in existing_lines:
        sline = line.strip()
        if sline and not sline.startswith("#") and "=" in sline:
            k = sline.split("=", 1)[0].strip()
            if k in new_data:
                new_lines.append(f"{k}={new_data[k]}\n")
                written_keys.add(k)
                continue
        new_lines.append(line)

    for k, v in new_data.items():
        if k not in written_keys:
            new_lines.append(f"{k}={v}\n")
            written_keys.add(k)
        # Synchronize live process os.environ immediately
        os.environ[k] = str(v)

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"[ERROR] Failed to write {env_path}: {e}")

    return load_config()

def update_config_key(key: str, val):
    """Update a specific configuration key and persist to env file"""
    return save_config({key: val})

def get_rules_summary() -> str:
    """Return formatted HTML summary of current dynamic rules"""
    cfg = load_config()
    ip_limit = cfg.get("DEFAULT_IP_LIMIT", 1)
    quota_gb = cfg.get("DEFAULT_QUOTA_GB", 350)
    suspend_min = cfg.get("SUSPEND_DURATION_MINUTES", 10)
    auto_suspend = "Aktif (ON)" if cfg.get("AUTO_SUSPEND_ENABLED", 1) else "Nonaktif (OFF)"
    p_monthly = cfg.get("PRICE_MONTHLY", 8000)
    p_payg_daily = cfg.get("PRICE_PAYG_DAILY", 300)
    p_payg_10gb = cfg.get("PRICE_PAYG_10GB", 1000)
    quota_str = f"{quota_gb} GB" if quota_gb > 0 else "Unlimited"

    return (
        f"⚙️ <b>ATURAN & TARIF DINAMIS SAAT INI:</b>\n\n"
        f"• 🌐 <b>Limit IP Default</b>: <code>{ip_limit} IP</code> / Akun\n"
        f"• 📦 <b>Limit Kuota Default</b>: <code>{quota_str}</code> / Akun\n"
        f"• ⏱️ <b>Durasi Suspen Pelanggaran</b>: <code>{suspend_min} Menit</code>\n"
        f"• 🛡️ <b>Auto-Suspen Multi-Login</b>: <b>{auto_suspend}</b>\n"
        f"• 💵 <b>Harga Paket Bulanan</b>: <code>Rp {p_monthly:,}</code> / 30 Hari\n"
        f"• ⚡ <b>Harga PAYG Harian</b>: <code>Rp {p_payg_daily:,}</code> / Hari\n"
        f"• ⚡ <b>Harga PAYG Kuota 10GB</b>: <code>Rp {p_payg_10gb:,}</code>\n"
    )

def is_admin(user_id) -> bool:
    """Check if user_id is configured as an admin (supports single ID or comma/space separated list)"""
    if not user_id:
        return False
    cfg = load_config()
    raw = str(cfg.get("ADMIN_ID", "")).strip()
    if not raw:
        return False
    admin_ids = [a.strip() for a in raw.replace(",", " ").replace(";", " ").split() if a.strip()]
    return str(user_id) in admin_ids



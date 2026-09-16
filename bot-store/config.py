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
    
    # Load from file if exists
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k in config:
                            if isinstance(config[k], int):
                                try:
                                    config[k] = int(v)
                                except ValueError:
                                    pass
                            else:
                                config[k] = v
        except Exception as e:
            print(f"[WARN] Failed to read {env_path}: {e}")

    # Override with OS environment variables if set
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
                
    return config

def save_config(new_data: dict):
    config = load_config()
    config.update(new_data)
    env_path = get_env_path()
    os.makedirs(os.path.dirname(env_path), exist_ok=True)
    
    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# SATSET Telegram Store Bot Configuration\n")
        for k, v in config.items():
            f.write(f"{k}={v}\n")
    return config

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


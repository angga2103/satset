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
    "DEFAULT_IP_LIMIT": 2,
    "DEFAULT_QUOTA_GB": 0,  # 0 = unlimited
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

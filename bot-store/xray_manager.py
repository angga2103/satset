import os
import re
import json
import base64
import uuid as uuid_pkg
import datetime
import subprocess
import logging

logger = logging.getLogger("xray_manager")

CONFIG_FILE = "/etc/xray/config.json"
DOMAIN_FILE = "/etc/xray/domain"
IP_FILE = "/etc/xray/ipvps"

def get_domain() -> str:
    """Get server domain or fallback IP"""
    if os.path.exists(DOMAIN_FILE):
        try:
            with open(DOMAIN_FILE, "r") as f:
                d = f.read().strip()
                if d:
                    return d
        except Exception:
            pass

    if os.path.exists(IP_FILE):
        try:
            with open(IP_FILE, "r") as f:
                d = f.read().strip()
                if d:
                    return d
        except Exception:
            pass

    # Fallback to local / environment
    return os.environ.get("SERVER_DOMAIN", "satset.vpn")

def restart_xray() -> bool:
    """Restart Xray service safely"""
    if os.path.exists("/bin/systemctl") or os.path.exists("/usr/bin/systemctl"):
        try:
            subprocess.run(["systemctl", "restart", "xray"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception as e:
            logger.error(f"Failed to restart xray: {e}")
            return False
    return True

def username_exists(username: str) -> bool:
    """Check if username already exists in Xray config"""
    if not os.path.exists(CONFIG_FILE):
        return False
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            # Look for username marker or email
            pattern = rf'"{re.escape(username)}"'
            return bool(re.search(pattern, content))
    except Exception:
        return False

def inject_xray_config(marker: str, entry_lines: list) -> bool:
    """Inject configuration lines directly after a marker in config.json"""
    if not os.path.exists(CONFIG_FILE):
        logger.warning(f"Config file {CONFIG_FILE} not found (local dev mode)")
        return True

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        injected = False
        for line in lines:
            new_lines.append(line)
            if marker in line and not injected:
                # Add newline and entries
                for entry in entry_lines:
                    new_lines.append(entry + "\n")
                injected = True

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return injected
    except Exception as e:
        logger.error(f"Failed to inject config for marker {marker}: {e}")
        return False

def remove_xray_config(protocol: str, username: str) -> bool:
    """Remove client configuration from config.json"""
    if not os.path.exists(CONFIG_FILE):
        return True

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        # Regex patterns for different protocol markers
        # VMess: ### {user} ... \n},{...
        # VLess: #& {user} ... \n},{...
        # Trojan: #! {user} ... \n},{...
        # Shadowsocks: #@& {user} ... \n},{...
        patterns = [
            rf'### {re.escape(username)} [^\n]*\n}},\{{[^\n]*',
            rf'#& {re.escape(username)} [^\n]*\n}},\{{[^\n]*',
            rf'#! {re.escape(username)} [^\n]*\n}},\{{[^\n]*',
            rf'#@& {re.escape(username)} [^\n]*\n}},\{{[^\n]*',
        ]

        modified = content
        for pat in patterns:
            modified = re.sub(pat, '', modified)

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(modified)
            
        return True
    except Exception as e:
        logger.error(f"Failed to remove user {username} from config: {e}")
        return False

def create_vmess(username: str, days: int = 30, quota_gb: int = 0, ip_limit: int = 2) -> dict:
    domain = get_domain()
    user_uuid = str(uuid_pkg.uuid4())
    now = datetime.datetime.now()
    exp_date = (now + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    exp_human = (now + datetime.timedelta(days=days)).strftime("%d %b, %Y")

    # Format JSON links
    ws_tls_json = {
        "v": "2", "ps": username, "add": domain, "port": "443",
        "id": user_uuid, "aid": "0", "net": "ws", "path": "/vmess",
        "type": "none", "host": domain, "tls": "tls"
    }
    ws_ntls_json = {
        "v": "2", "ps": username, "add": domain, "port": "80",
        "id": user_uuid, "aid": "0", "net": "ws", "path": "/vmess",
        "type": "none", "host": domain, "tls": "none"
    }
    grpc_json = {
        "v": "2", "ps": username, "add": domain, "port": "443",
        "id": user_uuid, "aid": "0", "net": "grpc", "path": "vmess-grpc",
        "type": "none", "host": domain, "tls": "tls"
    }

    link_tls = "vmess://" + base64.b64encode(json.dumps(ws_tls_json).encode()).decode()
    link_ntls = "vmess://" + base64.b64encode(json.dumps(ws_ntls_json).encode()).decode()
    link_grpc = "vmess://" + base64.b64encode(json.dumps(grpc_json).encode()).decode()

    # Inject into config.json
    entry1 = f'### {username} {exp_date}'
    entry2 = f'}},{{"id": "{user_uuid}","alterId": 0,"email": "{username}"'
    inject_xray_config("#vmess", [entry1, entry2])
    inject_xray_config("#vmessgrpc", [entry1, entry2])

    # Save to db and quotas
    os.makedirs("/etc/vmess", exist_ok=True)
    with open("/etc/vmess/.vmess.db", "a", encoding="utf-8") as f:
        f.write(f"### {username} {exp_date} {user_uuid} \n")

    if quota_gb > 0:
        quota_bytes = quota_gb * 1024 * 1024 * 1024
        with open(f"/etc/vmess/{username}", "w") as f:
            f.write(str(quota_bytes))

    if ip_limit > 0:
        os.makedirs("/etc/limit/vmess/ip", exist_ok=True)
        with open(f"/etc/limit/vmess/ip/{username}", "w") as f:
            f.write(str(ip_limit))

    restart_xray()

    return {
        "protocol": "vmess",
        "username": username,
        "uuid": user_uuid,
        "domain": domain,
        "exp_date": exp_date,
        "exp_human": exp_human,
        "quota_gb": quota_gb,
        "ip_limit": ip_limit,
        "link_tls": link_tls,
        "link_ntls": link_ntls,
        "link_grpc": link_grpc,
        "primary_link": link_tls
    }

def create_vless(username: str, days: int = 30, quota_gb: int = 0, ip_limit: int = 2) -> dict:
    domain = get_domain()
    user_uuid = str(uuid_pkg.uuid4())
    now = datetime.datetime.now()
    exp_date = (now + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    exp_human = (now + datetime.timedelta(days=days)).strftime("%d %b, %Y")

    link_tls = f"vless://{user_uuid}@{domain}:443?path=/vless&security=tls&encryption=none&type=ws&host={domain}&sni={domain}#{username}"
    link_ntls = f"vless://{user_uuid}@{domain}:80?path=/vless&encryption=none&type=ws&host={domain}#{username}"
    link_grpc = f"vless://{user_uuid}@{domain}:443?mode=gun&security=tls&encryption=none&type=grpc&serviceName=vless-grpc&sni={domain}#{username}"

    entry1 = f'#& {username} {exp_date}'
    entry2 = f'}},{{"id": "{user_uuid}","email": "{username}"'
    inject_xray_config("#vless", [entry1, entry2])
    inject_xray_config("#vlessgrpc", [entry1, entry2])

    os.makedirs("/etc/vless", exist_ok=True)
    with open("/etc/vless/.vless.db", "a", encoding="utf-8") as f:
        f.write(f"#& {username} {exp_date} {user_uuid} {quota_gb} {ip_limit}\n")

    if quota_gb > 0:
        quota_bytes = quota_gb * 1024 * 1024 * 1024
        with open(f"/etc/vless/{username}", "w") as f:
            f.write(str(quota_bytes))

    if ip_limit > 0:
        os.makedirs("/etc/limit/vless/ip", exist_ok=True)
        with open(f"/etc/limit/vless/ip/{username}", "w") as f:
            f.write(str(ip_limit))

    restart_xray()

    return {
        "protocol": "vless",
        "username": username,
        "uuid": user_uuid,
        "domain": domain,
        "exp_date": exp_date,
        "exp_human": exp_human,
        "quota_gb": quota_gb,
        "ip_limit": ip_limit,
        "link_tls": link_tls,
        "link_ntls": link_ntls,
        "link_grpc": link_grpc,
        "primary_link": link_tls
    }

def create_trojan(username: str, days: int = 30, quota_gb: int = 0, ip_limit: int = 2) -> dict:
    domain = get_domain()
    user_uuid = str(uuid_pkg.uuid4())
    now = datetime.datetime.now()
    exp_date = (now + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    exp_human = (now + datetime.timedelta(days=days)).strftime("%d %b, %Y")

    link_tls = f"trojan://{user_uuid}@{domain}:443?path=%2Ftrojan-ws&security=tls&host={domain}&type=ws&sni={domain}#{username}"
    link_grpc = f"trojan://{user_uuid}@{domain}:443?mode=gun&security=tls&type=grpc&serviceName=trojan-grpc&sni={domain}#{username}"

    entry1 = f'#! {username} {exp_date}'
    entry2 = f'}},{{"password": "{user_uuid}","email": "{username}"'
    inject_xray_config("#trojanws", [entry1, entry2])
    inject_xray_config("#trojangrpc", [entry1, entry2])

    os.makedirs("/etc/trojan", exist_ok=True)
    with open("/etc/trojan/.trojan.db", "a", encoding="utf-8") as f:
        f.write(f"#! {username} {exp_date} {user_uuid} {quota_gb} {ip_limit}\n")

    if quota_gb > 0:
        quota_bytes = quota_gb * 1024 * 1024 * 1024
        with open(f"/etc/trojan/{username}", "w") as f:
            f.write(str(quota_bytes))

    if ip_limit > 0:
        os.makedirs("/etc/limit/trojan/ip", exist_ok=True)
        with open(f"/etc/limit/trojan/ip/{username}", "w") as f:
            f.write(str(ip_limit))

    restart_xray()

    return {
        "protocol": "trojan",
        "username": username,
        "uuid": user_uuid,
        "domain": domain,
        "exp_date": exp_date,
        "exp_human": exp_human,
        "quota_gb": quota_gb,
        "ip_limit": ip_limit,
        "link_tls": link_tls,
        "link_ntls": "",
        "link_grpc": link_grpc,
        "primary_link": link_tls
    }

def create_shadowsocks(username: str, days: int = 30, quota_gb: int = 0, ip_limit: int = 2) -> dict:
    domain = get_domain()
    user_uuid = str(uuid_pkg.uuid4())
    cipher = "aes-128-gcm"
    now = datetime.datetime.now()
    exp_date = (now + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    exp_human = (now + datetime.timedelta(days=days)).strftime("%d %b, %Y")

    cipher_key = f"{cipher}:{user_uuid}"
    key_b64 = base64.b64encode(cipher_key.encode()).decode()

    link_tls = f"ss://{key_b64}@{domain}:443?plugin=xray-plugin;mux=0;path=/ss-ws;host={domain};tls#{username}"
    link_grpc = f"ss://{key_b64}@{domain}:443?plugin=xray-plugin;mux=0;serviceName=ss-grpc;host={domain};tls#{username}"

    entry1 = f'#@& {username} {exp_date}'
    entry2 = f'}},{{"password": "{user_uuid}","method": "{cipher}","email": "{username}"'
    inject_xray_config("#ssws", [entry1, entry2])
    inject_xray_config("#ssgrpc", [entry1, entry2])

    os.makedirs("/etc/shadowsocks", exist_ok=True)
    with open("/etc/shadowsocks/.shadowsocks.db", "a", encoding="utf-8") as f:
        f.write(f"#@& {username} {exp_date} {user_uuid} {quota_gb} {ip_limit}\n")

    if quota_gb > 0:
        quota_bytes = quota_gb * 1024 * 1024 * 1024
        with open(f"/etc/shadowsocks/{username}", "w") as f:
            f.write(str(quota_bytes))

    if ip_limit > 0:
        os.makedirs("/etc/limit/shadowsocks/ip", exist_ok=True)
        with open(f"/etc/limit/shadowsocks/ip/{username}", "w") as f:
            f.write(str(ip_limit))

    restart_xray()

    return {
        "protocol": "shadowsocks",
        "username": username,
        "uuid": user_uuid,
        "domain": domain,
        "exp_date": exp_date,
        "exp_human": exp_human,
        "quota_gb": quota_gb,
        "ip_limit": ip_limit,
        "link_tls": link_tls,
        "link_ntls": "",
        "link_grpc": link_grpc,
        "primary_link": link_tls
    }

def create_account(protocol: str, username: str, days: int = 30, quota_gb: int = 0, ip_limit: int = 2) -> dict:
    protocol = protocol.lower()
    if protocol == "vmess":
        return create_vmess(username, days, quota_gb, ip_limit)
    elif protocol == "vless":
        return create_vless(username, days, quota_gb, ip_limit)
    elif protocol == "trojan":
        return create_trojan(username, days, quota_gb, ip_limit)
    elif protocol in ["shadowsocks", "ss"]:
        return create_shadowsocks(username, days, quota_gb, ip_limit)
    else:
        raise ValueError(f"Protokol tidak didukung: {protocol}")

def delete_account(protocol: str, username: str) -> bool:
    protocol = protocol.lower()
    remove_xray_config(protocol, username)

    # Clean files
    for base in [f"/etc/{protocol}", f"/etc/limit/{protocol}/ip"]:
        fpath = os.path.join(base, username)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass

    restart_xray()
    return True

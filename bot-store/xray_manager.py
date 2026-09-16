import os
import re
import json
import base64
import time
import uuid as uuid_pkg
import datetime
import subprocess
import logging
from config import load_config
import database

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
    """Check if username already exists in Xray config or system users"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                pattern = rf'"{re.escape(username)}"'
                if re.search(pattern, content):
                    return True
        except Exception:
            pass

    if os.path.exists("/etc/passwd"):
        try:
            with open("/etc/passwd", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith(f"{username}:"):
                        return True
        except Exception:
            pass

    if os.path.exists("/etc/ssh/.ssh.db"):
        try:
            with open("/etc/ssh/.ssh.db", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[1] == username:
                        return True
        except Exception:
            pass

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

def create_ssh(username: str, password: str = None, days: int = 30, ip_limit: int = 2) -> dict:
    domain = get_domain()
    ip_server = domain
    if os.path.exists(IP_FILE):
        try:
            with open(IP_FILE, "r") as f:
                ip_server = f.read().strip() or domain
        except Exception:
            pass

    if not password:
        password = "sat" + "".join(re.findall(r"[0-9]", str(uuid_pkg.uuid4())))[:5]

    now = datetime.datetime.now()
    exp_date = (now + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    exp_human = (now + datetime.timedelta(days=days)).strftime("%d %b, %Y")

    if os.path.exists("/usr/sbin/useradd") or os.path.exists("/sbin/useradd"):
        try:
            subprocess.run(
                ["useradd", "-e", exp_date, "-s", "/bin/false", "-M", username],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            p = subprocess.Popen(["chpasswd"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p.communicate(input=f"{username}:{password}".encode())
        except Exception as e:
            logger.error(f"Failed to create system user {username}: {e}")

    os.makedirs("/etc/ssh", exist_ok=True)
    os.makedirs("/detail/ssh", exist_ok=True)
    os.makedirs("/etc/limit/ssh/ip", exist_ok=True)

    db_path = "/etc/ssh/.ssh.db"
    try:
        if os.path.exists(db_path):
            with open(db_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            new_lines = [l for l in lines if not l.startswith(f"### {username} ")]
            with open(db_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        with open(db_path, "a", encoding="utf-8") as f:
            f.write(f"### {username} {exp_date} {password} {ip_limit}\n")
    except Exception as e:
        logger.error(f"Failed to save to {db_path}: {e}")

    try:
        with open(f"/etc/limit/ssh/ip/{username}", "w") as f:
            f.write(str(ip_limit))
    except Exception:
        pass

    payload_ws = f"GET / HTTP/1.1[crlf]Host: {domain}[crlf]Upgrade: websocket[crlf][crlf]"
    ssh_link = f"ssh://{username}:{password}@{domain}:443"

    return {
        "protocol": "ssh",
        "username": username,
        "password": password,
        "uuid": password,
        "domain": domain,
        "ip_server": ip_server,
        "exp_date": exp_date,
        "exp_human": exp_human,
        "quota_gb": 0,
        "ip_limit": ip_limit,
        "port_openssh": "22",
        "port_dropbear": "109, 143",
        "port_ssl": "443, 777",
        "port_ws_ntls": "80, 8080, 8880",
        "port_ws_tls": "443, 8443",
        "port_badvpn": "7100, 7200, 7300",
        "payload_ws": payload_ws,
        "link_tls": ssh_link,
        "link_ntls": ssh_link,
        "link_grpc": "",
        "primary_link": ssh_link
    }

def delete_ssh(username: str) -> bool:
    if os.path.exists("/usr/sbin/userdel") or os.path.exists("/sbin/userdel"):
        try:
            subprocess.run(["userdel", "-f", username], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    db_path = "/etc/ssh/.ssh.db"
    if os.path.exists(db_path):
        try:
            with open(db_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            new_lines = [l for l in lines if not l.startswith(f"### {username} ")]
            with open(db_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            pass

    for fpath in [f"/detail/ssh/{username}.txt", f"/etc/limit/ssh/ip/{username}"]:
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except Exception:
                pass
    return True

def create_account(protocol: str, username: str, days: int = 30, quota_gb: int = None, ip_limit: int = None) -> dict:
    protocol = protocol.lower()
    cfg = load_config()
    if quota_gb is None:
        quota_gb = cfg.get("DEFAULT_QUOTA_GB", 350)
    if ip_limit is None:
        ip_limit = cfg.get("DEFAULT_IP_LIMIT", 1)

    if protocol == "vmess":
        return create_vmess(username, days, quota_gb, ip_limit)
    elif protocol == "vless":
        return create_vless(username, days, quota_gb, ip_limit)
    elif protocol == "trojan":
        return create_trojan(username, days, quota_gb, ip_limit)
    elif protocol in ["shadowsocks", "ss"]:
        return create_shadowsocks(username, days, quota_gb, ip_limit)
    elif protocol in ["ssh", "openssh", "dropbear"]:
        return create_ssh(username, days=days, ip_limit=ip_limit)
    else:
        raise ValueError(f"Protokol tidak didukung: {protocol}")

def delete_account(protocol: str, username: str) -> bool:
    protocol = protocol.lower()
    if protocol in ["ssh", "openssh", "dropbear"]:
        return delete_ssh(username)

    remove_xray_config(protocol, username)

    # Clean db entries if exists
    db_file = f"/etc/{protocol}/.{protocol}.db"
    if os.path.exists(db_file):
        try:
            with open(db_file, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            new_lines = [l for l in lines if not re.search(rf'^(?:###|#&|#!|#@&)\s+{re.escape(username)}\s+', l)]
            with open(db_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
        except Exception:
            pass

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

def format_bytes(bytes_count: int) -> str:
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 ** 2:
        return f"{bytes_count / 1024:.1f} KB"
    elif bytes_count < 1024 ** 3:
        return f"{bytes_count / (1024 ** 2):.1f} MB"
    else:
        return f"{bytes_count / (1024 ** 3):.2f} GB"

def get_active_sessions() -> dict:
    """Scan Xray access log and SSH active logins for distinct connected IPs per user.
    Returns: {username: [ip1, ip2, ...]}
    """
    sessions = {}
    
    # 1. Parse Xray access.log (Bounded tail read to prevent OOM on large logs)
    access_log = "/var/log/xray/access.log"
    if os.path.exists(access_log):
        try:
            CHUNK_SIZE = 131072  # Read at most last 128KB
            with open(access_log, "rb") as f:
                f.seek(0, os.SEEK_END)
                fsize = f.tell()
                f.seek(max(0, fsize - CHUNK_SIZE), os.SEEK_SET)
                raw_bytes = f.read()
            lines = raw_bytes.decode("utf-8", errors="ignore").splitlines()[-1500:]
            
            for line in lines:
                user = None
                ip = None
                
                email_m = re.search(r'email:\s*([a-zA-Z0-9_]+)', line)
                if email_m:
                    user = email_m.group(1).strip()
                
                ip_m = re.search(r'(?:from\s+|(?:\s|^))([0-9]{1,3}(?:\.[0-9]{1,3}){3}):\d+', line)
                if ip_m:
                    ip = ip_m.group(1).strip()
                    
                if user and ip:
                    if ip not in ["127.0.0.1", "0.0.0.0"]:
                        if user not in sessions:
                            sessions[user] = set()
                        sessions[user].add(ip)
        except Exception as e:
            logger.warning(f"Error reading Xray access log: {e}")

    # 2. Parse SSH sessions from 'who'
    try:
        p = subprocess.run(["who"], capture_output=True, text=True, timeout=2)
        if p.returncode == 0:
            for line in p.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    u = parts[0]
                    ip_match = re.search(r'\(([0-9]{1,3}(?:\.[0-9]{1,3}){3})\)', line)
                    if ip_match:
                        ssh_ip = ip_match.group(1)
                        if u not in sessions:
                            sessions[u] = set()
                        sessions[u].add(ssh_ip)
    except Exception:
        pass

    return {u: sorted(list(ips)) for u, ips in sessions.items()}

def get_user_usage_and_status(username: str, protocol: str = None) -> dict:
    """Retrieve detailed usage and status of a user (quota, limit IP, active IPs, suspension)"""
    if not protocol:
        acc = database.get_account_by_username(username)
        if acc:
            protocol = acc.get("protocol", "vmess").lower()
        else:
            protocol = "vmess"
    else:
        protocol = protocol.lower()

    # 1. Used quota from /etc/limit/{protocol}/{username}
    used_bytes = 0
    limit_file = f"/etc/limit/{protocol}/{username}"
    if os.path.exists(limit_file):
        try:
            with open(limit_file, "r") as f:
                content = f.read().strip()
                if content.isdigit():
                    used_bytes = int(content)
        except Exception:
            pass

    # 2. Query Xray API stats if available
    xray_bin = "/usr/local/bin/xray" if os.path.exists("/usr/local/bin/xray") else "xray"
    try:
        cmd = [xray_bin, "api", "stats", "--server=127.0.0.1:10000", "-name", f"user>>>{username}>>>traffic>>>downlink"]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
        if p.returncode == 0 and "value" in p.stdout:
            match = re.search(r'"value":\s*"?(\d+)"?', p.stdout)
            if match:
                used_bytes += int(match.group(1))
    except Exception:
        pass

    # 3. Quota limit
    quota_bytes = 0
    quota_file = f"/etc/{protocol}/{username}"
    if os.path.exists(quota_file):
        try:
            with open(quota_file, "r") as f:
                content = f.read().strip()
                if content.isdigit():
                    quota_bytes = int(content)
        except Exception:
            pass
    if quota_bytes == 0:
        acc = database.get_account_by_username(username)
        if acc and acc.get("quota_gb"):
            quota_bytes = int(acc["quota_gb"]) * (1024 ** 3)

    # 4. IP limit
    ip_limit = 1
    ip_file = f"/etc/limit/{protocol}/ip/{username}"
    if os.path.exists(ip_file):
        try:
            with open(ip_file, "r") as f:
                content = f.read().strip()
                if content.isdigit():
                    ip_limit = int(content)
        except Exception:
            pass
    else:
        acc = database.get_account_by_username(username)
        if acc and acc.get("ip_limit"):
            ip_limit = int(acc["ip_limit"])
        else:
            cfg = load_config()
            ip_limit = cfg.get("DEFAULT_IP_LIMIT", 1)

    # 5. Active IPs
    active_sessions = get_active_sessions()
    active_ips = active_sessions.get(username, [])

    # 6. Lock / Suspended status
    acc = database.get_account_by_username(username)
    is_locked = False
    locked_until = None
    lock_reason = None
    remaining_sec = 0

    if acc and acc.get("status") == "suspended":
        is_locked = True
        locked_until = acc.get("locked_until")
        lock_reason = acc.get("lock_reason", "multi_login")
        if locked_until:
            try:
                dt_lock = datetime.datetime.strptime(locked_until, "%Y-%m-%d %H:%M:%S")
                diff = (dt_lock - datetime.datetime.now()).total_seconds()
                remaining_sec = max(0, int(diff))
            except Exception:
                pass
    else:
        if os.path.exists("/etc/user_locks.db"):
            try:
                with open("/etc/user_locks.db", "r") as f:
                    for line in f:
                        parts = line.strip().split(":")
                        if len(parts) >= 2 and parts[1] == username:
                            is_locked = True
                            if len(parts) >= 3 and parts[2].isdigit():
                                lock_ts = int(parts[2])
                                remaining_sec = max(0, 600 - int(time.time() - lock_ts))
                            break
            except Exception:
                pass

    percent = 0.0
    if quota_bytes > 0:
        percent = min(100.0, (used_bytes / quota_bytes) * 100)

    filled = int(percent / 10)
    progress_bar = "█" * filled + "░" * (10 - filled)

    return {
        "username": username,
        "protocol": protocol,
        "used_bytes": used_bytes,
        "used_human": format_bytes(used_bytes),
        "quota_bytes": quota_bytes,
        "quota_human": format_bytes(quota_bytes) if quota_bytes > 0 else "Unlimited",
        "quota_gb": quota_bytes / (1024 ** 3) if quota_bytes > 0 else 0,
        "percent": percent,
        "progress_bar": progress_bar,
        "active_ips": active_ips,
        "active_ip_count": len(active_ips),
        "ip_limit": ip_limit,
        "is_locked": is_locked,
        "locked_until": locked_until,
        "lock_reason": lock_reason,
        "remaining_sec": remaining_sec,
        "remaining_human": f"{remaining_sec // 60}m {remaining_sec % 60}s" if remaining_sec > 0 else "Selesai"
    }

def suspend_account(protocol: str, username: str, duration_minutes: int = 10, reason: str = "multi_login") -> str:
    """Safely suspend user account for specified duration without corrupting config files"""
    protocol = protocol.lower()
    logger.info(f"Suspending {protocol} user '{username}' for {duration_minutes}m (reason: {reason})")

    if protocol in ["ssh", "openssh", "dropbear"]:
        if os.path.exists("/usr/sbin/usermod") or os.path.exists("/sbin/usermod"):
            subprocess.run(["usermod", "-L", username], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-u", username], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        remove_xray_config(protocol, username)
        restart_xray()

    locked_until = database.lock_account_db(username, duration_minutes, reason)

    # Sync /etc/user_locks.db for shell script compatibility
    lock_file = "/etc/user_locks.db"
    now_ts = int(time.time())
    try:
        lines = []
        if os.path.exists(lock_file):
            with open(lock_file, "r") as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith(f"{protocol}:{username}:")]
        lines.append(f"{protocol}:{username}:{now_ts}:{duration_minutes}:{reason}")
        os.makedirs(os.path.dirname(lock_file), exist_ok=True)
        with open(lock_file, "w") as f:
            for l in lines:
                f.write(l + "\n")
    except Exception as e:
        logger.warning(f"Failed to write to {lock_file}: {e}")

    return locked_until

def unsuspend_account(protocol: str, username: str) -> bool:
    """Safely restore user account into active service"""
    protocol = protocol.lower()
    logger.info(f"Unsuspending {protocol} user '{username}'")

    acc = database.get_account_by_username(username)
    user_uuid = acc.get("uuid") if acc else None
    exp_date = acc.get("exp_date") if acc else datetime.datetime.now().strftime("%Y-%m-%d")

    # If UUID not in database, attempt to find in /etc/{protocol}/.{protocol}.db
    if not user_uuid and protocol not in ["ssh", "openssh", "dropbear"]:
        db_file = f"/etc/{protocol}/.{protocol}.db"
        if os.path.exists(db_file):
            try:
                with open(db_file, "r") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 4 and parts[1] == username:
                            exp_date = parts[2]
                            user_uuid = parts[3]
                            break
            except Exception:
                pass

    if protocol in ["ssh", "openssh", "dropbear"]:
        if os.path.exists("/usr/sbin/usermod") or os.path.exists("/sbin/usermod"):
            subprocess.run(["usermod", "-U", username], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        if user_uuid:
            if protocol == "vmess":
                entry1 = f'### {username} {exp_date}'
                entry2 = f'}},{{"id": "{user_uuid}","alterId": 0,"email": "{username}"'
                inject_xray_config("#vmess", [entry1, entry2])
                inject_xray_config("#vmessgrpc", [entry1, entry2])
            elif protocol == "vless":
                entry1 = f'#& {username} {exp_date}'
                entry2 = f'}},{{"id": "{user_uuid}","email": "{username}"'
                inject_xray_config("#vless", [entry1, entry2])
                inject_xray_config("#vlessgrpc", [entry1, entry2])
            elif protocol == "trojan":
                entry1 = f'#! {username} {exp_date}'
                entry2 = f'}},{{"password": "{user_uuid}","email": "{username}"'
                inject_xray_config("#trojanws", [entry1, entry2])
                inject_xray_config("#trojangrpc", [entry1, entry2])
            elif protocol in ["shadowsocks", "ss"]:
                cipher = "aes-128-gcm"
                entry1 = f'#@& {username} {exp_date}'
                entry2 = f'}},{{"password": "{user_uuid}","method": "{cipher}","email": "{username}"'
                inject_xray_config("#ssws", [entry1, entry2])
                inject_xray_config("#ssgrpc", [entry1, entry2])
            restart_xray()
        else:
            logger.warning(f"Could not restore Xray config for {username}: UUID not found")

    database.unlock_account_db(username)

    # Clean /etc/user_locks.db
    lock_file = "/etc/user_locks.db"
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r") as f:
                lines = [l.strip() for l in f if l.strip() and not l.startswith(f"{protocol}:{username}:")]
            with open(lock_file, "w") as f:
                for l in lines:
                    f.write(l + "\n")
        except Exception:
            pass

    return True

def reset_user_quota(protocol: str, username: str) -> bool:
    """Reset accumulated traffic usage of a user to 0"""
    protocol = protocol.lower()
    limit_file = f"/etc/limit/{protocol}/{username}"
    try:
        os.makedirs(os.path.dirname(limit_file), exist_ok=True)
        with open(limit_file, "w") as f:
            f.write("0")
    except Exception as e:
        logger.error(f"Failed to reset quota file {limit_file}: {e}")

    xray_bin = "/usr/local/bin/xray" if os.path.exists("/usr/local/bin/xray") else "xray"
    try:
        subprocess.run([xray_bin, "api", "stats", "--server=127.0.0.1:10000", "-name", f"user>>>{username}>>>traffic>>>downlink", "-reset"],
                       capture_output=True, timeout=1)
        subprocess.run([xray_bin, "api", "stats", "--server=127.0.0.1:10000", "-name", f"user>>>{username}>>>traffic>>>uplink", "-reset"],
                       capture_output=True, timeout=1)
    except Exception:
        pass
    return True

def set_user_quota(protocol: str, username: str, quota_gb: int) -> bool:
    """Set custom quota limit in GB for a specific user"""
    protocol = protocol.lower()
    quota_bytes = quota_gb * (1024 ** 3)
    quota_file = f"/etc/{protocol}/{username}"
    try:
        os.makedirs(os.path.dirname(quota_file), exist_ok=True)
        with open(quota_file, "w") as f:
            f.write(str(quota_bytes))
    except Exception as e:
        logger.error(f"Failed to write quota file {quota_file}: {e}")

    database.update_account_rules(username, quota_gb=quota_gb)
    return True

def set_user_ip_limit(protocol: str, username: str, ip_limit: int) -> bool:
    """Set custom maximum IP limit for a specific user"""
    protocol = protocol.lower()
    ip_file = f"/etc/limit/{protocol}/ip/{username}"
    try:
        os.makedirs(os.path.dirname(ip_file), exist_ok=True)
        with open(ip_file, "w") as f:
            f.write(str(ip_limit))
    except Exception as e:
        logger.error(f"Failed to write IP limit file {ip_file}: {e}")

    database.update_account_rules(username, ip_limit=ip_limit)
    return True


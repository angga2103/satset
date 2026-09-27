#!/usr/bin/env python3
"""
SATSET Node Agent Daemon
Multi-Server / Multi-Node Orchestration Agent for Xray & SSH Services.
Enables Master VPS to monitor, create/renew/delete accounts, and control
services (Xray, SSH, BadVPN, Nginx, RAM/Logs, WARP) remotely via authenticated REST API.
"""

import os
import sys
import json
import time
import secrets
import shutil
import socket
import threading
import subprocess
import re
import urllib.request
import urllib.error
try:
    from http.server import ThreadingHTTPServer as HTTPServer, BaseHTTPRequestHandler
except ImportError:
    from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Base directories & file paths
CONFIG_DIR = "/etc/satset" if (os.path.exists("/etc/satset") or os.name != "nt") else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".satset")
KEY_FILE = os.path.join(CONFIG_DIR, "node-key.txt")
CONF_FILE = os.path.join(CONFIG_DIR, "node.conf")
CLUSTER_FILE = os.path.join(CONFIG_DIR, "cluster.json")
PORT_DEFAULT = 9090
VERSION = "1.0.0"

# Add bot-store path so we can import xray_manager and database if present
STORE_DIR = "/etc/satset/bot-store"
LOCAL_STORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot-store")
for p in [STORE_DIR, LOCAL_STORE]:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    import xray_manager
except ImportError:
    xray_manager = None

try:
    import database
except ImportError:
    database = None

def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(CONFIG_DIR, 0o700)
        except Exception:
            pass

def get_or_create_api_key() -> str:
    ensure_config_dir()
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8") as f:
                k = f.read().strip()
                if k and len(k) >= 16:
                    return k
        except Exception:
            pass

    new_key = secrets.token_hex(24)  # 48-char secure random hex key
    try:
        with open(KEY_FILE, "w", encoding="utf-8") as f:
            f.write(new_key + "\n")
        if os.name != "nt":
            os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass
    return new_key

def get_node_port() -> int:
    if os.path.exists(CONF_FILE):
        try:
            with open(CONF_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("PORT="):
                        return int(line.split("=", 1)[1].strip())
        except Exception:
            pass
    return PORT_DEFAULT

def get_public_ip() -> str:
    for fpath in ["/etc/xray/ipvps", "/root/ipvps", "/var/lib/ipvps.conf"]:
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip().replace("IP=", "").strip()
                        if line and not line.startswith("#") and ":" not in line:
                            return line
            except Exception:
                pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def get_node_domain() -> str:
    domain_file = "/etc/xray/domain"
    if os.path.exists(domain_file):
        try:
            with open(domain_file, "r", encoding="utf-8") as f:
                d = f.read().strip()
                if d:
                    return d
        except Exception:
            pass
    return get_public_ip()

def get_connection_token() -> str:
    host = get_node_domain()
    port = get_node_port()
    key = get_or_create_api_key()
    return f"satset-node://{host}:{port}#key={key}"

# -------------------------------------------------------------
# Cluster State & Role Management (Master, Cabang, Standalone)
# -------------------------------------------------------------
def load_cluster_state() -> dict:
    ensure_config_dir()
    default_state = {
        "role": "standalone",
        "master": {},
        "nodes": []
    }
    if os.path.exists(CLUSTER_FILE):
        try:
            with open(CLUSTER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("role", "standalone")
                    data.setdefault("master", {})
                    data.setdefault("nodes", [])
                    return data
        except Exception:
            pass
    return default_state

def save_cluster_state(state: dict):
    ensure_config_dir()
    try:
        with open(CLUSTER_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        if os.name != "nt":
            os.chmod(CLUSTER_FILE, 0o600)
    except Exception:
        pass

def parse_node_token(token_str: str) -> dict:
    token_str = token_str.strip()
    if token_str.startswith("satset://") or token_str.startswith("satset-node://"):
        try:
            parsed = urlparse(token_str)
            params = parse_qs(parsed.query)
            host = parsed.netloc.split(":")[0] if parsed.netloc else params.get("host", [""])[0]
            port = int(parsed.port) if parsed.port else int(params.get("port", [PORT_DEFAULT])[0])
            key = params.get("key", [""])[0]
            name = params.get("name", [""])[0]
            flag = params.get("flag", ["🌐"])[0]
            if "#key=" in token_str and not key:
                key = token_str.split("#key=")[1].split("&")[0].split()[0]
            return {
                "host": host,
                "port": port,
                "key": key,
                "name": name or f"Node-{host}",
                "flag": flag
            }
        except Exception:
            pass
    if token_str.startswith("{") and token_str.endswith("}"):
        try:
            d = json.loads(token_str)
            return {
                "host": d.get("host", ""),
                "port": int(d.get("port", PORT_DEFAULT)),
                "key": d.get("key", d.get("api_key", "")),
                "name": d.get("name", ""),
                "flag": d.get("flag", "🌐")
            }
        except Exception:
            pass
    parts = token_str.split(":")
    if len(parts) >= 3:
        return {
            "host": parts[0],
            "port": int(parts[1]),
            "key": parts[2],
            "name": f"Node-{parts[0]}",
            "flag": "🌐"
        }
    return {}

def remote_node_request(host: str, port: int, api_key: str, method: str, endpoint: str, body: dict = None, timeout: float = 6.0) -> tuple:
    url = f"http://{host}:{port}{endpoint}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": f"SatSet-Node-Agent/{VERSION}"
    }
    data_bytes = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            body_res = resp.read().decode("utf-8")
            try:
                return code, json.loads(body_res)
            except Exception:
                return code, {"raw": body_res}
    except urllib.error.HTTPError as e:
        body_res = e.read().decode("utf-8") if e.fp else ""
        try:
            return e.code, json.loads(body_res)
        except Exception:
            return e.code, {"error": body_res or str(e)}
    except Exception as e:
        return 0, {"error": str(e)}

def register_as_node(master_host: str, master_domain: str, master_name: str = "") -> tuple:
    state = load_cluster_state()
    current_role = state.get("role", "standalone")

    # Mutex Check 1: Master cannot become a node
    if current_role == "master" and len(state.get("nodes", [])) > 0:
        return False, f"VPS ini adalah VPS Master dengan {len(state['nodes'])} cabang terhubung. Tidak dapat dijadikan sebagai cabang!"

    # Mutex Check 2: Already a node of another master
    current_master = state.get("master", {})
    if current_role == "node" and current_master.get("host") and current_master.get("host") != master_host:
        return False, f"VPS ini sudah menginduk ke VPS Master lain ({current_master.get('domain', current_master.get('host'))}). Putuskan koneksi terlebih dahulu!"

    state["role"] = "node"
    state["master"] = {
        "host": master_host,
        "domain": master_domain or master_host,
        "name": master_name or f"Master-{master_host}",
        "registered_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    state["nodes"] = []
    save_cluster_state(state)
    return True, "Berhasil terdaftar sebagai VPS Cabang"

def unregister_as_node() -> tuple:
    state = load_cluster_state()
    state["role"] = "standalone"
    state["master"] = {}
    save_cluster_state(state)
    return True, "VPS ini berhasil di-reset menjadi Standalone (bebas dari Master)"

def master_add_node(token_str: str) -> tuple:
    state = load_cluster_state()
    current_role = state.get("role", "standalone")

    # Mutex Check: A Cabang (Worker) CANNOT add other nodes!
    if current_role == "node":
        master_dom = state.get("master", {}).get("domain", "Master")
        return False, f"VPS ini berstatus sebagai VPS CABANG yang menginduk ke '{master_dom}'. VPS Cabang TIDAK DAPAT menambahkan VPS cabang lain!", {}

    info = parse_node_token(token_str)
    host = info.get("host")
    port = info.get("port", PORT_DEFAULT)
    key = info.get("key")
    name = info.get("name") or f"Node-{host}"
    flag = info.get("flag") or "🌐"

    if not host or not key:
        return False, "Format token tidak valid atau API key tidak ditemukan.", {}

    my_ip = get_public_ip()
    my_domain = get_node_domain()
    if host in [my_ip, my_domain, "127.0.0.1", "localhost"]:
        return False, "Tidak dapat menambahkan VPS sendiri sebagai cabang!", {}

    for n in state.get("nodes", []):
        if n.get("host") == host or n.get("domain") == host:
            return False, f"Node dengan host/domain '{host}' sudah ada di daftar cabang!", {}

    # 1. Test connectivity
    t_start = time.time()
    code, status_res = remote_node_request(host, port, key, "GET", "/api/status", timeout=6.0)
    if code != 200:
        err_msg = status_res.get("message", status_res.get("error", "Koneksi gagal / timeout"))
        return False, f"Gagal menghubungi VPS Cabang di {host}:{port} ({err_msg})", {}

    ping_ms = max(1, int((time.time() - t_start) * 1000))
    node_domain = status_res.get("domain", host)

    # 2. Handshake: Register master info on remote node
    handshake_payload = {
        "master_host": my_ip,
        "master_domain": my_domain,
        "master_name": socket.gethostname()
    }
    h_code, h_res = remote_node_request(host, port, key, "POST", "/api/cluster/register_master", body=handshake_payload, timeout=6.0)
    if h_code != 200:
        err_h = h_res.get("message", h_res.get("error", "Handshake ditolak oleh VPS Cabang"))
        return False, f"Handshake gagal: {err_h}", {}

    # 3. Add to master state
    next_id = max([n.get("id", 0) for n in state.get("nodes", [])] + [0]) + 1
    new_node_obj = {
        "id": next_id,
        "name": name,
        "host": host,
        "domain": node_domain,
        "port": port,
        "api_key": key,
        "flag": flag,
        "status": "online",
        "ping_ms": ping_ms,
        "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
        "system_info": {
            "uptime": status_res.get("uptime", "-"),
            "cpu_percent": status_res.get("cpu", {}).get("cpu_percent", 0),
            "ram_used_mb": status_res.get("ram", {}).get("used_mb", 0),
            "ram_total_mb": status_res.get("ram", {}).get("total_mb", 0),
            "services": status_res.get("services", {})
        }
    }
    nodes_list = state.get("nodes", [])
    nodes_list.append(new_node_obj)
    state["nodes"] = nodes_list
    state["role"] = "master"
    save_cluster_state(state)

    # 4. Sync with bot-store SQLite database if present
    if database:
        try:
            db_nodes = database.get_all_nodes()
            existing_db = any(dn.get("host") == host for dn in db_nodes)
            if not existing_db:
                database.add_node(name=name, host=host, port=port, api_key=key, flag=flag)
        except Exception:
            pass

    return True, f"VPS Cabang '{name}' ({node_domain}) berhasil dihubungkan ke Master!", new_node_obj

def master_remove_node(target: str) -> tuple:
    state = load_cluster_state()
    nodes = state.get("nodes", [])
    found = None
    remaining = []
    for n in nodes:
        if str(n.get("id")) == str(target) or n.get("host") == str(target) or n.get("domain") == str(target):
            found = n
        else:
            remaining.append(n)

    if not found:
        return False, f"Node '{target}' tidak ditemukan di cluster!"

    try:
        remote_node_request(found["host"], found["port"], found["api_key"], "POST", "/api/cluster/unregister_master", timeout=4.0)
    except Exception:
        pass

    state["nodes"] = remaining
    if len(remaining) == 0:
        state["role"] = "standalone"
    save_cluster_state(state)

    if database:
        try:
            for dn in database.get_all_nodes():
                if dn.get("host") == found["host"]:
                    database.delete_node(dn["id"])
        except Exception:
            pass

    return True, f"Node '{found.get('name', target)}' ({found.get('domain', found.get('host'))}) berhasil diputuskan dari cluster."

def refresh_cluster_nodes_status() -> list:
    state = load_cluster_state()
    if state.get("role") != "master":
        return []
    nodes = state.get("nodes", [])
    updated = False
    for n in nodes:
        host = n.get("host")
        port = n.get("port", PORT_DEFAULT)
        key = n.get("api_key")
        t_start = time.time()
        code, res = remote_node_request(host, port, key, "GET", "/api/status", timeout=3.0)
        if code == 200:
            n["status"] = "online"
            n["ping_ms"] = max(1, int((time.time() - t_start) * 1000))
            n["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if "domain" in res:
                n["domain"] = res["domain"]
            n["system_info"] = {
                "uptime": res.get("uptime", "-"),
                "cpu_percent": res.get("cpu", {}).get("cpu_percent", 0),
                "ram_used_mb": res.get("ram", {}).get("used_mb", 0),
                "ram_total_mb": res.get("ram", {}).get("total_mb", 0),
                "services": res.get("services", {})
            }
        else:
            n["status"] = "offline"
            n["ping_ms"] = -1
        updated = True
    if updated:
        save_cluster_state(state)
    return nodes


def get_system_uptime():
    try:
        with open("/proc/uptime", "r") as f:
            total_seconds = float(f.readline().split()[0])
            days = int(total_seconds // (24 * 3600))
            hours = int((total_seconds % (24 * 3600)) // 3600)
            mins = int((total_seconds % 3600) // 60)
            parts = []
            if days > 0:
                parts.append(f"{days} hari")
            if hours > 0 or days > 0:
                parts.append(f"{hours} jam")
            parts.append(f"{mins} menit")
            return int(total_seconds), ", ".join(parts)
    except Exception:
        return 0, "-"

def get_cpu_info():
    try:
        cores = os.cpu_count() or 1
        with open("/proc/loadavg", "r") as f:
            loads = [float(x) for x in f.read().split()[:3]]
        # Estimate cpu usage % from 1-min load average
        cpu_pct = min(100.0, round((loads[0] / cores) * 100, 1))
        return {
            "cores": cores,
            "load_1m": loads[0],
            "load_5m": loads[1],
            "load_15m": loads[2],
            "cpu_percent": cpu_pct
        }
    except Exception:
        return {"cores": 1, "load_1m": 0.0, "load_5m": 0.0, "load_15m": 0.0, "cpu_percent": 0.0}

def get_ram_info():
    try:
        meminfo = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    v = parts[1].strip().split()[0]
                    meminfo[k] = int(v)
        total_kb = meminfo.get("MemTotal", 1)
        avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        used_kb = max(0, total_kb - avail_kb)
        pct = round((used_kb / total_kb) * 100, 1)
        return {
            "total_mb": round(total_kb / 1024, 1),
            "used_mb": round(used_kb / 1024, 1),
            "free_mb": round(avail_kb / 1024, 1),
            "percent": pct
        }
    except Exception:
        return {"total_mb": 0, "used_mb": 0, "free_mb": 0, "percent": 0}

def get_disk_info():
    try:
        usage = shutil.disk_usage("/")
        total_gb = round(usage.total / (1024**3), 1)
        used_gb = round(usage.used / (1024**3), 1)
        free_gb = round(usage.free / (1024**3), 1)
        pct = round((usage.used / usage.total) * 100, 1)
        return {
            "total_gb": total_gb,
            "used_gb": used_gb,
            "free_gb": free_gb,
            "percent": pct
        }
    except Exception:
        return {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0}

def check_service_status(service_name: str) -> str:
    if os.name == "nt":
        return "active"
    try:
        res = subprocess.run(
            ["systemctl", "is-active", service_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0
        )
        return res.stdout.strip() or "inactive"
    except Exception:
        return "inactive"

def get_all_services_status() -> dict:
    svcs = {
        "xray": check_service_status("xray"),
        "dropbear": check_service_status("dropbear"),
        "ssh": check_service_status("ssh") if check_service_status("ssh") != "inactive" else check_service_status("sshd"),
        "nginx": check_service_status("nginx"),
        "ws_stunnel": check_service_status("ws-stunnel"),
        "badvpn": check_service_status("badvpn-udpgw@7100"),
        "warp": check_service_status("warp-svc"),
        "fail2ban": check_service_status("fail2ban"),
        "cron": check_service_status("cron")
    }
    return svcs

def get_active_sessions_safe() -> list:
    if xray_manager and hasattr(xray_manager, "get_active_sessions"):
        try:
            return xray_manager.get_active_sessions()
        except Exception:
            pass
    return []

def count_local_accounts() -> int:
    total = 0
    # Xray config
    if os.path.exists("/etc/xray/config.json"):
        try:
            with open("/etc/xray/config.json", "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                # Count email fields in clients
                total += len([l for l in content.splitlines() if '"email":' in l])
        except Exception:
            pass
    # SSH users in passwd (UID >= 1000)
    if os.path.exists("/etc/passwd"):
        try:
            with open("/etc/passwd", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split(":")
                    if len(parts) >= 6:
                        try:
                            uid = int(parts[2])
                            if uid >= 1000 and uid < 65534:
                                total += 1
                        except ValueError:
                            pass
        except Exception:
            pass
    return total

class NodeRequestHandler(BaseHTTPRequestHandler):
    server_version = f"SATSET-Node/{VERSION}"

    def send_json(self, data: dict, status_code: int = 200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def verify_auth(self) -> bool:
        expected_key = get_or_create_api_key()
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if secrets.compare_digest(token, expected_key):
                return True

        x_key = self.headers.get("X-API-Key", "").strip()
        if x_key and secrets.compare_digest(x_key, expected_key):
            return True

        # Query param key hanya diizinkan untuk request read-only (GET)
        if self.command == "GET":
            parsed = urlparse(self.path)
            q = parse_qs(parsed.query)
            if "key" in q and q["key"]:
                if secrets.compare_digest(q["key"][0], expected_key):
                    return True
        return False

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self.verify_auth():
            self.send_json({"status": "error", "message": "Unauthorized: API Key tidak valid"}, 401)
            return

        if path == "/api/status" or path == "/status":
            uptime_sec, uptime_str = get_system_uptime()
            cpu = get_cpu_info()
            ram = get_ram_info()
            disk = get_disk_info()
            svcs = get_all_services_status()
            sessions = get_active_sessions_safe()

            hostname = socket.gethostname()
            resp = {
                "status": "success",
                "version": VERSION,
                "hostname": hostname,
                "domain": get_node_domain(),
                "ip": get_public_ip(),
                "port": get_node_port(),
                "uptime_seconds": uptime_sec,
                "uptime": uptime_str,
                "cpu": cpu,
                "ram": ram,
                "disk": disk,
                "services": svcs,
                "active_sessions_count": len(sessions),
                "total_accounts": count_local_accounts()
            }
            self.send_json(resp, 200)

        elif path == "/api/sessions":
            sessions = get_active_sessions_safe()
            self.send_json({
                "status": "success",
                "count": len(sessions),
                "sessions": sessions
            }, 200)

        elif path == "/api/warp/status":
            output = ""
            if os.path.exists("/usr/local/sbin/tune-warp"):
                try:
                    res = subprocess.run(["/usr/local/sbin/tune-warp", "status"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5.0)
                    output = res.stdout.strip()
                except Exception as e:
                    output = str(e)
            else:
                output = "Modul tune-warp tidak terpasang di node ini"
            self.send_json({"status": "success", "warp_status": output}, 200)

        elif path in ["/api/cluster/info", "/api/cluster"]:
            state = load_cluster_state()
            role = state.get("role", "standalone")
            if role == "node":
                master = state.get("master", {})
                m_host = master.get("host")
                status = "offline"
                ping_ms = -1
                if m_host:
                    t0 = time.time()
                    try:
                        s = socket.create_connection((m_host, 80), timeout=2.0)
                        s.close()
                        status = "online"
                        ping_ms = max(1, int((time.time() - t0) * 1000))
                    except Exception:
                        try:
                            s = socket.create_connection((m_host, 22), timeout=2.0)
                            s.close()
                            status = "online"
                            ping_ms = max(1, int((time.time() - t0) * 1000))
                        except Exception:
                            pass
                self.send_json({
                    "status": "success",
                    "role": "node",
                    "master": master,
                    "master_status": status,
                    "master_ping_ms": ping_ms,
                    "can_add_nodes": False
                }, 200)
            elif role == "master":
                nodes = refresh_cluster_nodes_status()
                self.send_json({
                    "status": "success",
                    "role": "master",
                    "nodes_count": len(nodes),
                    "nodes": nodes,
                    "can_add_nodes": True
                }, 200)
            else:
                self.send_json({
                    "status": "success",
                    "role": "standalone",
                    "token": get_connection_token(),
                    "api_key": get_or_create_api_key(),
                    "can_add_nodes": True
                }, 200)

        else:
            self.send_json({"status": "error", "message": f"Endpoint GET {path} tidak ditemukan"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if not self.verify_auth():
            self.send_json({"status": "error", "message": "Unauthorized: API Key tidak valid"}, 401)
            return

        # Parse request body
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as e:
            self.send_json({"status": "error", "message": f"Invalid JSON body: {e}"}, 400)
            return

        if path == "/api/account/create":
            if not xray_manager:
                self.send_json({"status": "error", "message": "Module xray_manager tidak ditemukan pada node ini"}, 500)
                return

            protocol = payload.get("protocol", "vmess").lower()
            username = payload.get("username", "").strip()
            days = int(payload.get("days", 30))
            quota_gb = payload.get("quota_gb")
            ip_limit = payload.get("ip_limit")

            if not username:
                self.send_json({"status": "error", "message": "Username harus diisi"}, 400)
                return

            if not re.match(r'^[a-zA-Z0-9_]{3,32}$', username):
                self.send_json({"status": "error", "message": "Format username tidak valid (hanya 3-32 alfanumerik / underscore)"}, 400)
                return

            try:
                acc = xray_manager.create_account(protocol, username, days=days, quota_gb=quota_gb, ip_limit=ip_limit)
                self.send_json({"status": "success", "account": acc}, 200)
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/account/delete":
            if not xray_manager:
                self.send_json({"status": "error", "message": "Module xray_manager tidak ditemukan"}, 500)
                return

            protocol = payload.get("protocol", "vmess").lower()
            username = payload.get("username", "").strip()
            if not username:
                self.send_json({"status": "error", "message": "Username harus diisi"}, 400)
                return

            try:
                ok = xray_manager.delete_account(protocol, username)
                self.send_json({"status": "success", "deleted": ok}, 200)
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/account/renew":
            if not xray_manager:
                self.send_json({"status": "error", "message": "Module xray_manager tidak ditemukan"}, 500)
                return

            protocol = payload.get("protocol", "vmess").lower()
            username = payload.get("username", "").strip()
            new_exp_date = payload.get("new_exp_date", "")
            user_uuid = payload.get("user_uuid")

            if not username or not new_exp_date:
                self.send_json({"status": "error", "message": "Username dan new_exp_date harus diisi"}, 400)
                return

            try:
                ok = xray_manager.renew_account(protocol, username, new_exp_date, user_uuid=user_uuid)
                self.send_json({"status": "success", "renewed": ok}, 200)
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/account/suspend":
            if not xray_manager:
                self.send_json({"status": "error", "message": "Module xray_manager tidak ditemukan"}, 500)
                return

            username = payload.get("username", "").strip()
            protocol = payload.get("protocol") or (xray_manager.detect_user_protocol(username) if hasattr(xray_manager, "detect_user_protocol") else "vmess")
            duration_minutes = int(payload.get("duration_minutes", 10))
            reason = payload.get("reason", "admin_suspended")
            try:
                xray_manager.suspend_account(protocol, username, duration_minutes=duration_minutes, reason=reason)
                self.send_json({"status": "success", "message": f"Akun {username} ({protocol}) berhasil disuspend"}, 200)
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/account/unsuspend":
            if not xray_manager:
                self.send_json({"status": "error", "message": "Module xray_manager tidak ditemukan"}, 500)
                return

            username = payload.get("username", "").strip()
            protocol = payload.get("protocol") or (xray_manager.detect_user_protocol(username) if hasattr(xray_manager, "detect_user_protocol") else "vmess")
            try:
                xray_manager.unsuspend_account(protocol, username)
                self.send_json({"status": "success", "message": f"Akun {username} ({protocol}) berhasil diaktifkan kembali"}, 200)
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/control/service":
            service = payload.get("service", "").lower()
            action = payload.get("action", "restart").lower()

            VALID_ACTIONS = ["start", "stop", "restart", "reload", "status"]
            if action not in VALID_ACTIONS:
                self.send_json({"status": "error", "message": f"Aksi '{action}' tidak valid (pilih: {', '.join(VALID_ACTIONS)})"}, 400)
                return

            cmds = []
            if service == "xray":
                cmds = [["systemctl", action, "xray"]]
            elif service in ["ssh", "dropbear"]:
                cmds = [
                    ["systemctl", action, "dropbear"],
                    ["systemctl", action, "ssh"]
                ]
            elif service == "badvpn":
                cmds = [
                    ["systemctl", action, "badvpn-udpgw@7100"],
                    ["systemctl", action, "badvpn-udpgw@7200"],
                    ["systemctl", action, "badvpn-udpgw@7300"]
                ]
            elif service == "nginx":
                cmds = [["systemctl", action, "nginx"]]
            elif service == "warp":
                cmds = [["systemctl", action, "warp-svc"]]
            elif service == "all":
                cmds = [
                    ["systemctl", "restart", "xray"],
                    ["systemctl", "restart", "dropbear"],
                    ["systemctl", "restart", "ssh"],
                    ["systemctl", "restart", "nginx"],
                    ["systemctl", "restart", "badvpn-udpgw@7100"],
                    ["systemctl", "restart", "badvpn-udpgw@7200"],
                    ["systemctl", "restart", "badvpn-udpgw@7300"]
                ]
            else:
                self.send_json({"status": "error", "message": f"Layanan '{service}' tidak dikenal"}, 400)
                return

            success = True
            if os.name != "nt":
                for cmd in cmds:
                    try:
                        subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10.0)
                    except Exception:
                        success = False

            self.send_json({
                "status": "success" if success else "warning",
                "message": f"Perintah '{action}' pada layanan '{service}' berhasil dieksekusi"
            }, 200)

        elif path == "/api/control/system":
            action = payload.get("action", "").lower()

            if action == "clean_ram":
                try:
                    subprocess.run(["sync"], check=False)
                    if os.path.exists("/proc/sys/vm/drop_caches"):
                        with open("/proc/sys/vm/drop_caches", "w") as f:
                            f.write("3\n")
                    ram = get_ram_info()
                    self.send_json({
                        "status": "success",
                        "message": "RAM Cache & Buffer berhasil dibersihkan",
                        "ram": ram
                    }, 200)
                except Exception as e:
                    self.send_json({"status": "error", "message": f"Gagal membersihkan RAM: {e}"}, 500)

            elif action == "clear_logs":
                try:
                    # Truncate log files safely
                    log_patterns = [
                        "/var/log/xray/access.log",
                        "/var/log/xray/error.log",
                        "/var/log/nginx/access.log",
                        "/var/log/nginx/error.log",
                        "/var/log/auth.log",
                        "/var/log/syslog"
                    ]
                    for lp in log_patterns:
                        if os.path.exists(lp):
                            try:
                                with open(lp, "w") as f:
                                    f.truncate(0)
                            except Exception:
                                pass
                    self.send_json({"status": "success", "message": "Log sistem dan Xray berhasil dibersihkan"}, 200)
                except Exception as e:
                    self.send_json({"status": "error", "message": f"Gagal membersihkan log: {e}"}, 500)

            elif action == "reboot":
                def do_delayed_reboot():
                    time.sleep(2.0)
                    subprocess.run(["systemctl", "reboot"], check=False)

                t = threading.Thread(target=do_delayed_reboot, daemon=True)
                t.start()
                self.send_json({"status": "success", "message": "Server node sedang memulai proses reboot dalam 2 detik..."}, 200)

            else:
                self.send_json({"status": "error", "message": f"Aksi sistem '{action}' tidak dikenal"}, 400)

        elif path == "/api/control/warp":
            warp_action = payload.get("action", "status").lower()
            warp_mode = payload.get("mode", "")

            if not os.path.exists("/usr/local/sbin/tune-warp"):
                self.send_json({"status": "error", "message": "Modul Smart WARP (/usr/local/sbin/tune-warp) tidak ditemukan"}, 404)
                return

            cmd = ["/usr/local/sbin/tune-warp", warp_action]
            if warp_mode:
                cmd.append(warp_mode)

            try:
                res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15.0)
                out = res.stdout.strip() or res.stderr.strip()
                self.send_json({"status": "success", "message": out}, 200)
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/cluster/register_master":
            m_host = payload.get("master_host", "")
            m_dom = payload.get("master_domain", m_host)
            m_name = payload.get("master_name", "")
            if not m_host:
                self.send_json({"status": "error", "message": "master_host wajib disertakan"}, 400)
                return
            ok, msg = register_as_node(m_host, m_dom, m_name)
            if ok:
                self.send_json({
                    "status": "success",
                    "message": msg,
                    "node_domain": get_node_domain(),
                    "node_ip": get_public_ip(),
                    "node_hostname": socket.gethostname()
                }, 200)
            else:
                self.send_json({"status": "error", "message": msg}, 400)

        elif path == "/api/cluster/unregister_master":
            ok, msg = unregister_as_node()
            self.send_json({"status": "success" if ok else "error", "message": msg}, 200 if ok else 400)

        elif path == "/api/cluster/add_node":
            token_in = payload.get("token", "")
            if not token_in:
                self.send_json({"status": "error", "message": "Token koneksi cabang wajib disertakan"}, 400)
                return
            ok, msg, node_obj = master_add_node(token_in)
            if ok:
                self.send_json({"status": "success", "message": msg, "node": node_obj}, 200)
            else:
                self.send_json({"status": "error", "message": msg}, 400)

        elif path == "/api/cluster/remove_node":
            target = payload.get("target", "") or payload.get("host", "") or str(payload.get("node_id", ""))
            if not target:
                self.send_json({"status": "error", "message": "Target ID atau Host node cabang wajib disertakan"}, 400)
                return
            ok, msg = master_remove_node(target)
            if ok:
                self.send_json({"status": "success", "message": msg}, 200)
            else:
                self.send_json({"status": "error", "message": msg}, 400)

        else:
            self.send_json({"status": "error", "message": f"Endpoint POST {path} tidak ditemukan"}, 404)

    def log_message(self, format, *args):
        # Suppress routine console logs unless error
        if args and str(args[1]) in ["401", "404", "500"]:
            super().log_message(format, *args)

def run_server(port: int = None):
    if port is None:
        port = get_node_port()

    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, NodeRequestHandler)
    print(f"[*] SATSET Node Agent v{VERSION} berjalan pada port {port}")
    print(f"[*] Token: {get_connection_token()}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Menutup Node Agent...")
        httpd.server_close()

def main():
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "token":
            print(get_connection_token())
            return
        elif cmd == "key":
            print(get_or_create_api_key())
            return
        elif cmd == "reset-key":
            new_key = secrets.token_hex(24)
            ensure_config_dir()
            with open(KEY_FILE, "w", encoding="utf-8") as f:
                f.write(new_key + "\n")
            if os.name != "nt":
                os.chmod(KEY_FILE, 0o600)
                subprocess.run(["systemctl", "restart", "satset-node"], check=False)
            print("[+] API Key berhasil di-reset!")
            print(f"[+] Token baru: {get_connection_token()}")
            return
        elif cmd == "status":
            print(f"SATSET Node Agent v{VERSION}")
            print(f"Status Service : {check_service_status('satset-node')}")
            print(f"Host / Domain  : {get_node_domain()}")
            print(f"Public IP      : {get_public_ip()}")
            print(f"Port           : {get_node_port()}")
            print(f"API Key        : {get_or_create_api_key()[:8]}... (tersembunyi)")
            print(f"Token Koneksi  : {get_connection_token()}")
            state = load_cluster_state()
            role = state.get("role", "standalone")
            if role == "master":
                print(f"Peran Cluster  : MASTER ({len(state.get('nodes', []))} Cabang Terhubung)")
            elif role == "node":
                m = state.get("master", {})
                print(f"Peran Cluster  : CABANG (Menginduk ke {m.get('domain', m.get('host', '-'))})")
            else:
                print(f"Peran Cluster  : STANDALONE (Siap Jadi Master / Cabang)")
            return
        elif cmd == "role":
            state = load_cluster_state()
            print(state.get("role", "standalone"))
            return
        elif cmd == "cluster":
            state = load_cluster_state()
            role = state.get("role", "standalone")
            print("==========================================")
            print(f"  SATSET CLUSTER STATUS: {role.upper()}")
            print("==========================================")
            if role == "master":
                nodes = refresh_cluster_nodes_status()
                print(f"Total Node Cabang: {len(nodes)}")
                for idx, n in enumerate(nodes, 1):
                    badge = "[ONLINE]" if n.get("status") == "online" else "[OFFLINE]"
                    ping = f"({n.get('ping_ms', -1)}ms)" if n.get("status") == "online" else ""
                    print(f" {idx}. {n.get('flag', '🌐')} {n.get('name', 'Node')} - {n.get('domain', n.get('host'))} {badge} {ping}")
            elif role == "node":
                m = state.get("master", {})
                print(f"Status: VPS Cabang (Worker)")
                print(f"Menginduk ke Master: {m.get('domain', m.get('host', '-'))} ({m.get('host', '-')})")
                print(f"Waktu Registrasi   : {m.get('registered_at', '-')}")
            else:
                print("Status: Standalone (Belum terhubung ke cluster)")
                print(f"Token untuk dihubungkan: {get_connection_token()}")
            print("==========================================")
            return
        elif cmd == "add-node":
            if len(sys.argv) < 3:
                print("Penggunaan: satset-node add-node <token_koneksi>")
                return
            token_arg = sys.argv[2]
            ok, msg, node_obj = master_add_node(token_arg)
            if ok:
                print(f"[+] Sukses: {msg}")
            else:
                print(f"[-] Gagal: {msg}")
            return
        elif cmd == "remove-node":
            if len(sys.argv) < 3:
                print("Penggunaan: satset-node remove-node <id_atau_host>")
                return
            target_arg = sys.argv[2]
            ok, msg = master_remove_node(target_arg)
            if ok:
                print(f"[+] Sukses: {msg}")
            else:
                print(f"[-] Gagal: {msg}")
            return
        elif cmd == "unlink-master":
            ok, msg = unregister_as_node()
            print(f"[+] {msg}")
            return
        elif cmd == "run":
            port = int(sys.argv[2]) if len(sys.argv) > 2 else get_node_port()
            run_server(port)
            return

    # Default if no arguments: run server
    run_server()

if __name__ == "__main__":
    main()

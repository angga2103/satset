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
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Base directories & file paths
CONFIG_DIR = "/etc/satset"
KEY_FILE = os.path.join(CONFIG_DIR, "node-key.txt")
CONF_FILE = os.path.join(CONFIG_DIR, "node.conf")
PORT_DEFAULT = 9090
VERSION = "1.0.0"

# Add bot-store path so we can import xray_manager if present
STORE_DIR = "/etc/satset/bot-store"
LOCAL_STORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot-store")
for p in [STORE_DIR, LOCAL_STORE]:
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)

try:
    import xray_manager
except ImportError:
    xray_manager = None

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
            username = payload.get("username", "")
            days = int(payload.get("days", 30))
            quota_gb = payload.get("quota_gb")
            ip_limit = payload.get("ip_limit")

            if not username:
                self.send_json({"status": "error", "message": "Username harus diisi"}, 400)
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
            username = payload.get("username", "")
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
            username = payload.get("username", "")
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

            username = payload.get("username", "")
            reason = payload.get("reason", "admin_suspended")
            try:
                xray_manager.suspend_account(username, reason=reason)
                self.send_json({"status": "success", "message": f"Akun {username} berhasil disuspend"}, 200)
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/account/unsuspend":
            if not xray_manager:
                self.send_json({"status": "error", "message": "Module xray_manager tidak ditemukan"}, 500)
                return

            username = payload.get("username", "")
            try:
                xray_manager.unsuspend_account(username)
                self.send_json({"status": "success", "message": f"Akun {username} berhasil diaktifkan kembali"}, 200)
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, 500)

        elif path == "/api/control/service":
            service = payload.get("service", "").lower()
            action = payload.get("action", "restart").lower()

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
            return
        elif cmd == "run":
            port = int(sys.argv[2]) if len(sys.argv) > 2 else get_node_port()
            run_server(port)
            return

    # Default if no arguments: run server
    run_server()

if __name__ == "__main__":
    main()

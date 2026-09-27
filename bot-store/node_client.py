#!/usr/bin/env python3
"""
SATSET Master Node Client
Dispatches VPN account operations, service controls, live monitoring,
and system maintenance to local Master VPS or remote Node VPSs.
"""

import os
import sys
import json
import time
import socket
import logging
import urllib.request
import urllib.error
import subprocess
from urllib.parse import urlparse

import database
import xray_manager

logger = logging.getLogger("node_client")

# --- Local Host Dispatcher (when node_id == 0) ---

def _get_local_uptime():
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

def _get_local_cpu():
    try:
        cores = os.cpu_count() or 1
        with open("/proc/loadavg", "r") as f:
            loads = [float(x) for x in f.read().split()[:3]]
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

def _get_local_ram():
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

def _get_local_disk():
    try:
        import shutil
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

def _check_local_service(service_name: str) -> str:
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

def _get_local_services():
    return {
        "xray": _check_local_service("xray"),
        "dropbear": _check_local_service("dropbear"),
        "ssh": _check_local_service("ssh") if _check_local_service("ssh") != "inactive" else _check_local_service("sshd"),
        "nginx": _check_local_service("nginx"),
        "ws_stunnel": _check_local_service("ws-stunnel"),
        "badvpn": _check_local_service("badvpn-udpgw@7100"),
        "warp": _check_local_service("warp-svc"),
        "fail2ban": _check_local_service("fail2ban"),
        "cron": _check_local_service("cron")
    }

def dispatch_local(endpoint: str, data: dict = None) -> dict:
    data = data or {}
    if endpoint == "/api/status":
        uptime_sec, uptime_str = _get_local_uptime()
        cpu = _get_local_cpu()
        ram = _get_local_ram()
        disk = _get_local_disk()
        svcs = _get_local_services()
        sessions = xray_manager.get_active_sessions()

        return {
            "status": "success",
            "version": "1.0.0",
            "hostname": socket.gethostname(),
            "domain": xray_manager.get_domain(),
            "ip": "127.0.0.1",
            "port": 9090,
            "uptime_seconds": uptime_sec,
            "uptime": uptime_str,
            "cpu": cpu,
            "ram": ram,
            "disk": disk,
            "services": svcs,
            "active_sessions_count": len(sessions),
            "total_accounts": len(sessions)
        }

    elif endpoint == "/api/sessions":
        sessions = xray_manager.get_active_sessions()
        return {"status": "success", "count": len(sessions), "sessions": sessions}

    elif endpoint == "/api/account/create":
        proto = data.get("protocol", "vmess")
        uname = data.get("username", "")
        days = data.get("days", 30)
        quota_gb = data.get("quota_gb")
        ip_limit = data.get("ip_limit")
        acc = xray_manager.create_account(proto, uname, days=days, quota_gb=quota_gb, ip_limit=ip_limit)
        return {"status": "success", "account": acc}

    elif endpoint == "/api/account/delete":
        proto = data.get("protocol", "vmess")
        uname = data.get("username", "")
        ok = xray_manager.delete_account(proto, uname)
        return {"status": "success", "deleted": ok}

    elif endpoint == "/api/account/renew":
        proto = data.get("protocol", "vmess")
        uname = data.get("username", "")
        new_exp_date = data.get("new_exp_date", "")
        user_uuid = data.get("user_uuid")
        ok = xray_manager.renew_account(proto, uname, new_exp_date, user_uuid=user_uuid)
        return {"status": "success", "renewed": ok}

    elif endpoint == "/api/account/suspend":
        uname = data.get("username", "")
        reason = data.get("reason", "admin_suspended")
        xray_manager.suspend_account(uname, reason=reason)
        return {"status": "success"}

    elif endpoint == "/api/account/unsuspend":
        uname = data.get("username", "")
        xray_manager.unsuspend_account(uname)
        return {"status": "success"}

    elif endpoint == "/api/control/service":
        svc = data.get("service", "").lower()
        act = data.get("action", "restart").lower()
        cmds = []
        if svc == "xray":
            cmds = [["systemctl", act, "xray"]]
        elif svc in ["ssh", "dropbear"]:
            cmds = [["systemctl", act, "dropbear"], ["systemctl", act, "ssh"]]
        elif svc == "badvpn":
            cmds = [
                ["systemctl", act, "badvpn-udpgw@7100"],
                ["systemctl", act, "badvpn-udpgw@7200"],
                ["systemctl", act, "badvpn-udpgw@7300"]
            ]
        elif svc == "nginx":
            cmds = [["systemctl", act, "nginx"]]
        elif svc == "warp":
            cmds = [["systemctl", act, "warp-svc"]]
        elif svc == "all":
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
            return {"status": "error", "message": f"Unknown service: {svc}"}

        if os.name != "nt":
            for cmd in cmds:
                subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"status": "success", "message": f"Service {svc} {act} executed"}

    elif endpoint == "/api/control/system":
        act = data.get("action", "").lower()
        if act == "clean_ram":
            if os.name != "nt":
                subprocess.run(["sync"], check=False)
                if os.path.exists("/proc/sys/vm/drop_caches"):
                    with open("/proc/sys/vm/drop_caches", "w") as f:
                        f.write("3\n")
            ram = _get_local_ram()
            return {"status": "success", "message": "RAM Cache dibersihkan", "ram": ram}
        elif act == "clear_logs":
            if os.name != "nt":
                for lp in ["/var/log/xray/access.log", "/var/log/xray/error.log", "/var/log/auth.log", "/var/log/syslog"]:
                    if os.path.exists(lp):
                        try:
                            with open(lp, "w") as f:
                                f.truncate(0)
                        except Exception:
                            pass
            return {"status": "success", "message": "File log lokal dibersihkan"}
        elif act == "reboot":
            return {"status": "warning", "message": "Reboot Master VPS tidak diizinkan melalui remote API cabang"}

    elif endpoint == "/api/control/warp":
        warp_act = data.get("action", "status")
        warp_mode = data.get("mode", "")
        if os.path.exists("/usr/local/sbin/tune-warp"):
            cmd = ["/usr/local/sbin/tune-warp", warp_act]
            if warp_mode:
                cmd.append(warp_mode)
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15.0)
            return {"status": "success", "message": res.stdout.strip() or res.stderr.strip()}
        return {"status": "error", "message": "tune-warp script not found on local master"}

    return {"status": "error", "message": f"Endpoint {endpoint} tidak didukung secara lokal"}

# --- Remote Node Dispatcher ---

def request_node(node: dict, endpoint: str, method: str = "GET", data: dict = None, timeout: float = 8.0) -> dict:
    if not node:
        return {"status": "error", "message": "Node tidak valid"}

    node_id = int(node.get("id", 0))
    if node_id == 0 or node.get("host") in ["127.0.0.1", "localhost"]:
        try:
            return dispatch_local(endpoint, data)
        except Exception as e:
            return {"status": "error", "message": f"Local execution error: {e}"}

    host = node.get("host", "").strip()
    port = int(node.get("port", 9090))
    api_key = node.get("api_key", "").strip()

    url = f"http://{host}:{port}{endpoint}"
    headers = {
        "User-Agent": "SATSET-Master-Client/1.0",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    req_data = json.dumps(data).encode("utf-8") if data is not None and method == "POST" else None
    req = urllib.request.Request(url, data=req_data, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            return json.loads(resp_body)
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
            err_json = json.loads(err_body)
            return {"status": "error", "message": err_json.get("message", f"HTTP {e.code}")}
        except Exception:
            return {"status": "error", "message": f"HTTP Error {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"status": "error", "message": f"Koneksi gagal: {e.reason}"}
    except socket.timeout:
        return {"status": "error", "message": f"Koneksi timeout ({timeout}s)"}
    except Exception as e:
        return {"status": "error", "message": f"Request error: {e}"}

# --- Connection Token Parser ---

def parse_connection_token(raw: str) -> dict:
    raw = raw.strip()
    # Format 1: satset-node://host:port#key=xxx
    if raw.startswith("satset-node://"):
        cleaned = raw.replace("satset-node://", "")
        # Check if auth style: key@host:port
        if "@" in cleaned:
            parts = cleaned.split("@", 1)
            api_key = parts[0]
            host_port = parts[1]
            if ":" in host_port:
                h, p = host_port.split(":", 1)
                port = int(p)
            else:
                h, port = host_port, 9090
            return {"host": h, "port": port, "api_key": api_key, "name": f"Node-{h}"}

        # Fragment style: host:port#key=xxx
        host_part = cleaned
        api_key = ""
        if "#" in host_part:
            host_part, frag = host_part.split("#", 1)
            for param in frag.split("&"):
                if param.startswith("key="):
                    api_key = param.split("=", 1)[1]
        if ":" in host_part:
            h, p = host_part.split(":", 1)
            port = int(p)
        else:
            h, port = host_part, 9090
        return {"host": h, "port": port, "api_key": api_key, "name": f"Node-{h}"}

    # Format 2: JSON format {"host": "...", "port": 9090, "api_key": "..."}
    if raw.startswith("{") and raw.endswith("}"):
        data = json.loads(raw)
        return {
            "host": data["host"],
            "port": int(data.get("port", 9090)),
            "api_key": data.get("api_key") or data.get("key", ""),
            "name": data.get("name", f"Node-{data['host']}")
        }

    # Format 3: colon separated IP:PORT:KEY or IP:PORT:KEY:NAME
    parts = raw.split(":")
    if len(parts) >= 3:
        h = parts[0].strip()
        port = int(parts[1].strip())
        key = parts[2].strip()
        name = parts[3].strip() if len(parts) >= 4 else f"Node-{h}"
        return {"host": h, "port": port, "api_key": key, "name": name}

    raise ValueError("Format token tidak dikenali. Gunakan format satset-node://host:port#key=xxx atau IP:PORT:KEY")

# --- High Level API Methods ---

def test_connection(host: str, port: int, api_key: str, timeout: float = 6.0) -> dict:
    node_temp = {"id": -1, "host": host, "port": port, "api_key": api_key}
    t0 = time.time()
    res = request_node(node_temp, "/api/status", method="GET", timeout=timeout)
    elapsed_ms = int((time.time() - t0) * 1000)
    if res.get("status") == "success":
        res["ping_ms"] = elapsed_ms
        return res
    res["ping_ms"] = 0
    return res

def ping_node(node_id: int) -> dict:
    node = database.get_node_by_id(node_id)
    if not node:
        return {"status": "error", "message": f"Node {node_id} not found"}

    if node_id == 0:
        local_st = dispatch_local("/api/status")
        local_st["ping_ms"] = 0
        local_st["is_online"] = True
        return local_st

    t0 = time.time()
    res = request_node(node, "/api/status", method="GET", timeout=5.0)
    elapsed_ms = int((time.time() - t0) * 1000)

    if res.get("status") == "success":
        res["ping_ms"] = elapsed_ms
        res["is_online"] = True
        # Cache status in database
        sys_info_json = json.dumps({
            "hostname": res.get("hostname"),
            "domain": res.get("domain"),
            "uptime": res.get("uptime"),
            "cpu": res.get("cpu"),
            "ram": res.get("ram"),
            "disk": res.get("disk"),
            "services": res.get("services"),
            "active_users": res.get("active_sessions_count", 0),
            "total_accounts": res.get("total_accounts", 0)
        })
        database.update_node_status(node_id, is_active=node.get("is_active", 1), ping_ms=elapsed_ms, system_info=sys_info_json)
    else:
        res["ping_ms"] = 0
        res["is_online"] = False

    return res

def get_all_nodes_summary() -> list:
    nodes = database.get_all_nodes()
    # Always include Master as node 0
    master_node = {
        "id": 0,
        "name": "Master VPS",
        "host": "127.0.0.1",
        "port": 9090,
        "flag": "👑",
        "is_active": 1,
        "is_master": True
    }
    all_nodes = [master_node] + nodes
    results = []

    for n in all_nodes:
        nid = n["id"]
        status = ping_node(nid)
        is_online = status.get("is_online", False)
        ping_ms = status.get("ping_ms", 0)

        cpu_val = status.get("cpu", {}).get("cpu_percent", 0)
        ram_val = status.get("ram", {}).get("percent", 0)
        disk_val = status.get("disk", {}).get("percent", 0)
        users = status.get("active_sessions_count", 0)

        results.append({
            "id": nid,
            "name": n.get("name", f"Node #{nid}"),
            "flag": n.get("flag", "🌐"),
            "host": n.get("host", ""),
            "port": n.get("port", 9090),
            "is_active": n.get("is_active", 1),
            "is_master": (nid == 0),
            "is_online": is_online,
            "ping_ms": ping_ms,
            "cpu_percent": cpu_val,
            "ram_percent": ram_val,
            "disk_percent": disk_val,
            "active_users": users,
            "raw_status": status
        })

    return results

def create_account(node_id: int, protocol: str, username: str, days: int = 30, quota_gb: int = None, ip_limit: int = None) -> dict:
    node = database.get_node_by_id(node_id)
    if not node:
        raise ValueError(f"Server Node ID {node_id} tidak ditemukan.")

    payload = {
        "protocol": protocol,
        "username": username,
        "days": days,
        "quota_gb": quota_gb,
        "ip_limit": ip_limit
    }

    res = request_node(node, "/api/account/create", method="POST", data=payload, timeout=15.0)
    if res.get("status") == "success" and "account" in res:
        acc = res["account"]
        # Tag account with node details
        acc["node_id"] = node_id
        acc["node_name"] = node.get("name", "Master VPS")
        acc["node_flag"] = node.get("flag", "🌐")
        return acc
    else:
        err_msg = res.get("message", "Gagal membuat akun di server node")
        raise RuntimeError(err_msg)

def delete_account(node_id: int, protocol: str, username: str) -> bool:
    node = database.get_node_by_id(node_id)
    if not node:
        # Fallback to local
        return xray_manager.delete_account(protocol, username)

    payload = {"protocol": protocol, "username": username}
    res = request_node(node, "/api/account/delete", method="POST", data=payload, timeout=10.0)
    return res.get("status") == "success"

def renew_account(node_id: int, protocol: str, username: str, new_exp_date: str, user_uuid: str = None) -> bool:
    node = database.get_node_by_id(node_id)
    if not node:
        return xray_manager.renew_account(protocol, username, new_exp_date, user_uuid=user_uuid)

    payload = {
        "protocol": protocol,
        "username": username,
        "new_exp_date": new_exp_date,
        "user_uuid": user_uuid
    }
    res = request_node(node, "/api/account/renew", method="POST", data=payload, timeout=10.0)
    return res.get("status") == "success"

def suspend_account(node_id: int, username: str, reason: str = "admin_suspended") -> bool:
    node = database.get_node_by_id(node_id)
    if not node:
        xray_manager.suspend_account(username, reason)
        return True

    payload = {"username": username, "reason": reason}
    res = request_node(node, "/api/account/suspend", method="POST", data=payload, timeout=10.0)
    return res.get("status") == "success"

def unsuspend_account(node_id: int, username: str) -> bool:
    node = database.get_node_by_id(node_id)
    if not node:
        xray_manager.unsuspend_account(username)
        return True

    payload = {"username": username}
    res = request_node(node, "/api/account/unsuspend", method="POST", data=payload, timeout=10.0)
    return res.get("status") == "success"

def restart_service(node_id: int, service: str) -> dict:
    node = database.get_node_by_id(node_id)
    if not node:
        return {"status": "error", "message": f"Node ID {node_id} tidak ditemukan"}

    payload = {"service": service, "action": "restart"}
    return request_node(node, "/api/control/service", method="POST", data=payload, timeout=12.0)

def system_control(node_id: int, action: str) -> dict:
    node = database.get_node_by_id(node_id)
    if not node:
        return {"status": "error", "message": f"Node ID {node_id} tidak ditemukan"}

    payload = {"action": action}
    return request_node(node, "/api/control/system", method="POST", data=payload, timeout=10.0)

def warp_control(node_id: int, action: str, mode: str = None) -> dict:
    node = database.get_node_by_id(node_id)
    if not node:
        return {"status": "error", "message": f"Node ID {node_id} tidak ditemukan"}

    payload = {"action": action}
    if mode:
        payload["mode"] = mode
    return request_node(node, "/api/control/warp", method="POST", data=payload, timeout=15.0)

def get_node_sessions(node_id: int) -> dict:
    node = database.get_node_by_id(node_id)
    if not node:
        return {}

    res = request_node(node, "/api/sessions", method="GET", timeout=5.0)
    if res.get("status") == "success":
        raw = res.get("sessions", {})
        if isinstance(raw, dict):
            return raw
        elif isinstance(raw, list):
            res_dict = {}
            for item in raw:
                if isinstance(item, dict):
                    res_dict[item.get("username", "user")] = item.get("ips", [])
            return res_dict
    return {}

def get_all_active_sessions() -> dict:
    all_grouped = {}
    master_sessions = get_node_sessions(0)
    all_grouped[0] = {
        "node_name": "Master VPS",
        "node_flag": "👑",
        "sessions": master_sessions
    }
    for n in database.get_active_nodes():
        nid = n["id"]
        sess = get_node_sessions(nid)
        all_grouped[nid] = {
            "node_name": n.get("name", f"Node #{nid}"),
            "node_flag": n.get("flag", "🌐"),
            "sessions": sess
        }
    return all_grouped

CLUSTER_FILE = "/etc/satset/cluster.json"

def sync_cluster_json_from_db():
    try:
        nodes = database.get_all_nodes()
        os.makedirs(os.path.dirname(CLUSTER_FILE), exist_ok=True)
        role = "master" if len(nodes) > 0 else "standalone"
        cdata = {
            "role": role,
            "master": {},
            "nodes": [
                {
                    "id": n["id"],
                    "name": n.get("name", ""),
                    "host": n.get("host", ""),
                    "domain": n.get("domain") or n.get("host", ""),
                    "port": int(n.get("port", 9090)),
                    "api_key": n.get("api_key", ""),
                    "flag": n.get("flag", "🌐"),
                    "status": "online" if n.get("last_ping_ms", -1) >= 0 else "offline",
                    "ping_ms": n.get("last_ping_ms", 0),
                    "last_seen": n.get("last_seen", "")
                }
                for n in nodes
            ]
        }
        with open(CLUSTER_FILE, "w", encoding="utf-8") as f:
            json.dump(cdata, f, indent=2)
        if os.name != "nt":
            os.chmod(CLUSTER_FILE, 0o600)
    except Exception:
        pass

def register_node_with_handshake(token_str: str) -> dict:
    try:
        token_data = parse_connection_token(token_str)
    except Exception as e:
        return {"status": "error", "message": f"Format token tidak valid: {e}"}

    host = token_data["host"]
    port = token_data["port"]
    api_key = token_data["api_key"]
    name = token_data.get("name") or f"Node-{host}"
    flag = token_data.get("flag", "🌐")

    for en in database.get_all_nodes():
        if en.get("host") == host:
            return {"status": "error", "message": f"Server dengan host {host} sudah ada di daftar node!"}

    # 1. Test connection
    test_res = test_connection(host, port, api_key, timeout=7.0)
    if test_res.get("status") != "success":
        err = test_res.get("message", "Timeout / Gagal terhubung")
        return {"status": "error", "message": f"Gagal menghubungi node di {host}:{port}: {err}"}

    # 2. Handshake: Register master info on remote node
    my_ip = _get_local_ip()
    my_domain = _get_local_domain()
    temp_node = {"id": -1, "host": host, "port": port, "api_key": api_key}
    handshake_payload = {
        "master_host": my_ip,
        "master_domain": my_domain,
        "master_name": socket.gethostname()
    }
    h_res = request_node(temp_node, "/api/cluster/register_master", method="POST", data=handshake_payload, timeout=7.0)
    if h_res.get("status") != "success":
        err_h = h_res.get("message", "Handshake pendaftaran ditolak oleh VPS Cabang")
        return {"status": "error", "message": f"Handshake gagal: {err_h}"}

    node_domain = h_res.get("node_domain") or test_res.get("domain", host)
    ping_ms = test_res.get("ping_ms", 0)
    uptime = test_res.get("uptime", "-")

    # 3. Add to database
    node_id = database.add_node(name=name, host=host, port=port, api_key=api_key, flag=flag)
    sys_info_json = json.dumps({
        "hostname": test_res.get("hostname", name),
        "domain": node_domain,
        "uptime": uptime,
        "cpu": test_res.get("cpu"),
        "ram": test_res.get("ram"),
        "disk": test_res.get("disk"),
        "services": test_res.get("services")
    })
    database.update_node_status(node_id, is_active=1, ping_ms=ping_ms, system_info=sys_info_json)

    # 4. Sync /etc/satset/cluster.json
    sync_cluster_json_from_db()

    return {
        "status": "success",
        "node_id": node_id,
        "name": name,
        "host": host,
        "port": port,
        "domain": node_domain,
        "ping_ms": ping_ms,
        "uptime": uptime
    }

def unregister_node_with_handshake(node_id: int) -> dict:
    node = database.get_node_by_id(node_id)
    if not node:
        return {"status": "error", "message": "Node tidak ditemukan"}

    try:
        request_node(node, "/api/cluster/unregister_master", method="POST", data={}, timeout=4.0)
    except Exception:
        pass

    database.delete_node(node_id)
    sync_cluster_json_from_db()
    return {"status": "success", "message": f"Node #{node_id} berhasil diputuskan"}

#!/usr/bin/env python3
"""
SATSET WebSocket to SSH/Dropbear Tunneling Proxy (ws-stunnel)
Proxies incoming HTTP/WebSocket connections from Nginx (127.0.0.1:10015)
to local Dropbear (127.0.0.1:109) or OpenSSH (127.0.0.1:22).
"""

import sys
import socket
import select
import threading
import logging
import json
import os
import time
import re

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 10015
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 109   # Dropbear port (fallback to 22 OpenSSH if dropbear is down)
FALLBACK_PORT = 22  # OpenSSH port
BUFFER_SIZE = 65536
SESSION_FILE = "/run/satset/ws_sessions.json"

SESSION_MAP_LOCK = threading.Lock()
ACTIVE_WS_SESSIONS = {}

def record_ws_session(local_port: int, client_ip: str):
    if not local_port:
        return
    with SESSION_MAP_LOCK:
        ACTIVE_WS_SESSIONS[str(local_port)] = {
            "ip": client_ip,
            "connected_at": int(time.time())
        }
        _write_session_file()

def remove_ws_session(local_port: int):
    if not local_port:
        return
    with SESSION_MAP_LOCK:
        if str(local_port) in ACTIVE_WS_SESSIONS:
            ACTIVE_WS_SESSIONS.pop(str(local_port), None)
            _write_session_file()

def _write_session_file():
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        tmp = SESSION_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(ACTIVE_WS_SESSIONS, f)
        os.replace(tmp, SESSION_FILE)
    except Exception:
        pass

def extract_real_ip(initial_data: bytes, fallback_ip: str) -> str:
    try:
        header_text = initial_data.decode("latin1", errors="ignore")
        m_xff = re.search(r'(?i)x-forwarded-for:\s*([^\r\n]+)', header_text)
        if m_xff:
            raw_ips = [ip.strip() for ip in m_xff.group(1).split(",")]
            for rip in raw_ips:
                if re.match(r'^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$', rip):
                    if not (rip.startswith("10.") or rip.startswith("192.168.") or rip.startswith("127.")):
                        return rip
            if raw_ips and re.match(r'^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$', raw_ips[0]):
                return raw_ips[0]

        m_rip = re.search(r'(?i)x-real-ip:\s*([^\r\n]+)', header_text)
        if m_rip:
            rip = m_rip.group(1).strip()
            if re.match(r'^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$', rip):
                return rip
    except Exception:
        pass
    return fallback_ip

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ws-stunnel] %(levelname)s: %(message)s"
)
logger = logging.getLogger("ws-stunnel")

WS_RESPONSE_101 = (
    b"HTTP/1.1 101 Switching Protocols\r\n"
    b"Upgrade: websocket\r\n"
    b"Connection: Upgrade\r\n"
    b"\r\n"
)

HTTP_200_OK = (
    b"HTTP/1.1 200 OK\r\n"
    b"Content-Type: text/plain\r\n"
    b"Content-Length: 2\r\n"
    b"Connection: keep-alive\r\n"
    b"\r\n"
    b"OK"
)

def pipe_client_to_backend(src, dst, on_close=None):
    """Pipes traffic from client to Dropbear, stripping split/dummy HTTP payloads (e.g. HTTP/ 69)"""
    ssh_started = False
    buf = b""
    try:
        while True:
            r, _, _ = select.select([src], [], [], 30)
            if not r:
                # Idle timeout reached, socket is still alive; continue listening
                continue
            data = src.recv(BUFFER_SIZE)
            if not data:
                break

            if not ssh_started:
                buf += data
                # Check if we have received real SSH client identification
                if b"SSH-" in buf:
                    ssh_started = True
                    idx = buf.find(b"SSH-")
                    # Discard any junk before SSH- (like HTTP/ 69\r\n\r\n) and send real SSH banner
                    dst.sendall(buf[idx:])
                    buf = b""
                elif buf.startswith(b"HTTP/") or b"HTTP/" in buf or b"\r\n" in buf:
                    # Still junk HTTP payload or dummy split packet, discard or buffer until SSH-
                    if len(buf) > 8192:
                        # Prevent unbounded buffering if client is not sending SSH-
                        ssh_started = True
                        dst.sendall(buf)
                        buf = b""
                    continue
                else:
                    # Non-HTTP data, forward directly
                    ssh_started = True
                    dst.sendall(buf)
                    buf = b""
            else:
                dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            src.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            dst.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        src.close()
        dst.close()
        if on_close:
            try:
                on_close()
            except Exception:
                pass

def pipe_backend_to_client(src, dst, on_close=None):
    """Pipes traffic from Dropbear back to client"""
    try:
        while True:
            r, _, _ = select.select([src], [], [], 30)
            if not r:
                # Idle timeout reached, socket is still alive; continue listening
                continue
            data = src.recv(BUFFER_SIZE)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            src.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            dst.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        src.close()
        dst.close()
        if on_close:
            try:
                on_close()
            except Exception:
                pass

def handle_client(client_sock, client_addr):
    local_port = None
    try:
        client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        client_sock.settimeout(15.0)
        initial_data = b""
        
        # Read until double CRLF (or SSH banner for direct clients)
        while b"\r\n\r\n" not in initial_data:
            if initial_data.startswith(b"SSH-"):
                break
            chunk = client_sock.recv(4096)
            if not chunk:
                break
            initial_data += chunk
            if len(initial_data) > 65536:
                break

        if not initial_data:
            client_sock.close()
            return

        # Check if HTTP request or raw SSH
        is_http = (
            any(initial_data.startswith(m) for m in [b"GET ", b"POST ", b"CONNECT ", b"PATCH ", b"PUT ", b"HEAD ", b"OPTIONS ", b"TRACE ", b"PRI "])
            or b"upgrade: websocket" in initial_data.lower()
            or b"http/" in initial_data.lower()
        )
        
        # Connect to local SSH backend (Dropbear first, fallback to OpenSSH)
        backend_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        backend_connected = False
        
        try:
            backend_sock.connect((TARGET_HOST, TARGET_PORT))
            backend_connected = True
        except Exception:
            try:
                backend_sock.connect((TARGET_HOST, FALLBACK_PORT))
                backend_connected = True
            except Exception as e:
                logger.error(f"Cannot connect to SSH backend on port {TARGET_PORT} or {FALLBACK_PORT}: {e}")
                client_sock.close()
                return

        client_sock.settimeout(None)
        backend_sock.settimeout(None)

        try:
            client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            backend_sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            if hasattr(socket, "TCP_KEEPIDLE"):
                client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
                backend_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)
            if hasattr(socket, "TCP_KEEPINTVL"):
                client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
                backend_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            if hasattr(socket, "TCP_KEEPCNT"):
                client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
                backend_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 5)
        except Exception:
            pass

        # Record real client IP mapping for Dropbear local socket
        try:
            local_port = backend_sock.getsockname()[1]
            real_ip = extract_real_ip(initial_data, client_addr[0])
            record_ws_session(local_port, real_ip)
        except Exception:
            pass

        def on_session_close():
            if local_port:
                remove_ws_session(local_port)

        if is_http:
            # Upgrade WebSocket handshake
            client_sock.sendall(WS_RESPONSE_101)
            # If initial_data had trailing data after \r\n\r\n
            if b"\r\n\r\n" in initial_data:
                trailing = initial_data.split(b"\r\n\r\n", 1)[1]
                if trailing and b"SSH-" in trailing:
                    idx = trailing.find(b"SSH-")
                    backend_sock.sendall(trailing[idx:])
        else:
            # If client sent raw data, forward it
            backend_sock.sendall(initial_data)

        # Start two-way piping with split payload filtering
        t1 = threading.Thread(target=pipe_client_to_backend, args=(client_sock, backend_sock, on_session_close), daemon=True)
        t2 = threading.Thread(target=pipe_backend_to_client, args=(backend_sock, client_sock, on_session_close), daemon=True)
        t1.start()
        t2.start()

    except Exception as e:
        logger.debug(f"Client handler error from {client_addr}: {e}")
        if local_port:
            remove_ws_session(local_port)
        try:
            client_sock.close()
        except Exception:
            pass

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server.bind((LISTEN_HOST, LISTEN_PORT))
    except Exception as e:
        logger.fatal(f"Failed to bind to {LISTEN_HOST}:{LISTEN_PORT}: {e}")
        sys.exit(1)

    server.listen(1024)
    logger.info(f"SATSET WebSocket Tunnel Proxy listening on {LISTEN_HOST}:{LISTEN_PORT} -> Dropbear :{TARGET_PORT}")

    while True:
        try:
            client_sock, client_addr = server.accept()
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            t = threading.Thread(target=handle_client, args=(client_sock, client_addr), daemon=True)
            t.start()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Error accepting connection: {e}")

    server.close()

if __name__ == "__main__":
    main()

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

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 10015
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 109   # Dropbear port (fallback to 22 OpenSSH if dropbear is down)
FALLBACK_PORT = 22  # OpenSSH port
BUFFER_SIZE = 65536

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

def pipe_client_to_backend(src, dst):
    """Pipes traffic from client to Dropbear, stripping split/dummy HTTP payloads (e.g. HTTP/ 69)"""
    ssh_started = False
    buf = b""
    try:
        while True:
            r, _, _ = select.select([src], [], [], 60)
            if not r:
                break
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

def pipe_backend_to_client(src, dst):
    """Pipes traffic from Dropbear back to client"""
    try:
        while True:
            r, _, _ = select.select([src], [], [], 60)
            if not r:
                break
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

def handle_client(client_sock, client_addr):
    try:
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
        t1 = threading.Thread(target=pipe_client_to_backend, args=(client_sock, backend_sock), daemon=True)
        t2 = threading.Thread(target=pipe_backend_to_client, args=(backend_sock, client_sock), daemon=True)
        t1.start()
        t2.start()

    except Exception as e:
        logger.debug(f"Client handler error from {client_addr}: {e}")
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

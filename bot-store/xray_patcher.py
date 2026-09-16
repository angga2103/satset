#!/usr/bin/env python3
import os
import re
import sys
import json
import shutil
import urllib.request
import subprocess

CONFIG_PATH = "/etc/xray/config.json"
CONFIG_PATH = "/etc/xray/config.json"
ASSET_DIRS = ["/usr/local/share/xray", "/usr/share/xray"]

def find_xray_binary() -> str:
    """Locate xray executable on system"""
    bin_path = shutil.which("xray")
    if bin_path and os.path.exists(bin_path):
        return bin_path
    for p in ["/usr/local/bin/xray", "/usr/bin/xray"]:
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p
    return "/usr/local/bin/xray"

def download_file(url: str, dest_paths: list) -> bool:
    """Download file using curl, wget, or python urllib with timeout and User-Agent"""
    if not dest_paths:
        return False
    temp_path = dest_paths[0] + ".tmp"
    success = False

    # 1. Try curl
    if shutil.which("curl"):
        r = subprocess.run(["curl", "-fsSL", "--connect-timeout", "15", "-o", temp_path, url], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 1000:
            success = True

    # 2. Try wget
    if not success and shutil.which("wget"):
        r = subprocess.run(["wget", "-q", "--timeout=15", "-O", temp_path, url], check=False)
        if r.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 1000:
            success = True

    # 3. Fallback python urllib with custom User-Agent
    if not success:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
            with urllib.request.urlopen(req, timeout=15) as resp, open(temp_path, "wb") as out:
                shutil.copyfileobj(resp, out)
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 1000:
                success = True
        except Exception:
            pass

    if success:
        for p in dest_paths:
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                shutil.copy2(temp_path, p)
            except Exception:
                pass
        try:
            os.remove(temp_path)
        except Exception:
            pass
        return True

    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except Exception:
            pass
    return False

def ensure_assets():
    """Ensure geosite.dat and geoip.dat are present in asset dirs"""
    if not sys.platform.startswith("linux"):
        return
    for d in ASSET_DIRS:
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass

    assets = {
        "geosite.dat": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat",
        "geoip.dat": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat"
    }

    for fname, url in assets.items():
        dest_paths = [os.path.join(d, fname) for d in ASSET_DIRS]
        # Download if missing or too small
        any_valid = any(os.path.exists(p) and os.path.getsize(p) > 1000 for p in dest_paths)
        if not any_valid:
            try:
                print(f"[Xray Patcher] Mengunduh aset {fname}...")
                ok = download_file(url, dest_paths)
                if ok:
                    print(f"[Xray Patcher] [OK] {fname} berhasil diunduh.")
                else:
                    print(f"[Xray Patcher] [WARN] Tidak dapat mengunduh {fname}. Menggunakan aturan bawaan.")
            except Exception as e:
                print(f"[Xray Patcher] [WARN] Gagal mengunduh {fname}: {e}")

def test_xray_config(xray_bin: str, cfg_path: str) -> tuple:
    """Test Xray configuration across different CLI syntaxes and capture full diagnostic output"""
    if not os.path.exists(xray_bin):
        return True, "xray not found, skipping binary verification"

    env = os.environ.copy()
    for d in ASSET_DIRS:
        if os.path.exists(d):
            env["XRAY_LOCATION_ASSET"] = d
            break

    commands = [
        [xray_bin, "run", "-test", "-config", cfg_path],
        [xray_bin, "-test", "-config", cfg_path],
        [xray_bin, "test", "-config", cfg_path],
        [xray_bin, "-test", "-c", cfg_path],
        [xray_bin, "run", "-test", "-c", cfg_path]
    ]

    last_out = ""
    for cmd in commands:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=10)
            combined = f"{(res.stderr or '').strip()}\n{(res.stdout or '').strip()}".strip()
            if res.returncode == 0:
                return True, combined
            last_out = combined or f"exit code {res.returncode}"
        except Exception as e:
            last_out = str(e)

    return False, last_out

def generate_routing_and_dns_block(content: str) -> str:
    """Dynamically generate valid routing and dns JSON block matching host configuration"""
    # Detect appropriate blackhole tag in outbounds
    block_tag = "blocked"
    if '"tag": "blocked"' in content or '"tag":"blocked"' in content:
        block_tag = "blocked"
    elif '"tag": "block"' in content or '"tag":"block"' in content:
        block_tag = "block"
    elif '"tag": "reject"' in content or '"tag":"reject"' in content:
        block_tag = "reject"

    has_dns_out = '"tag": "dnsOut"' in content or '"tag":"dnsOut"' in content

    # Check asset availability
    has_geosite = any(os.path.exists(os.path.join(d, "geosite.dat")) for d in ASSET_DIRS)
    has_geoip = any(os.path.exists(os.path.join(d, "geoip.dat")) for d in ASSET_DIRS)

    rules = [
        {
            "inboundTag": ["api"],
            "outboundTag": "api",
            "type": "field"
        }
    ]

    if has_dns_out:
        rules.append({
            "inboundTag": ["dnsIn"],
            "outboundTag": "dnsOut",
            "type": "field"
        })

    # BitTorrent wire protocol block
    rules.append({
        "type": "field",
        "outboundTag": block_tag,
        "protocol": ["bittorrent"]
    })

    # Ads and Torrent tracker domains
    domain_list = [
        "torrent",
        "tracker",
        "thepiratebay",
        "1337x",
        "rarbg",
        "yts",
        "nyaa",
        "torrentz"
    ]
    if has_geosite:
        domain_list.insert(0, "geosite:category-ads-all")

    rules.append({
        "type": "field",
        "outboundTag": block_tag,
        "domain": domain_list
    })

    # Private IP protection
    if has_geoip:
        rules.append({
            "type": "field",
            "outboundTag": block_tag,
            "ip": ["geoip:private"]
        })
    else:
        rules.append({
            "type": "field",
            "outboundTag": block_tag,
            "ip": [
                "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "169.254.0.0/16",
                "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24", "192.168.0.0/16",
                "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "::1/128",
                "fc00::/7", "fe80::/10"
            ]
        })

    # Default direct rule
    rules.append({
        "type": "field",
        "outboundTag": "direct",
        "network": "tcp,udp"
    })

    routing = {
        "domainStrategy": "IPIfNonMatch",
        "rules": rules
    }

    dns = {
        "hosts": {
            "dns.google": "8.8.8.8",
            "cloudflare-dns.com": "1.1.1.1"
        },
        "servers": [
            "https://1.1.1.1/dns-query",
            "8.8.8.8",
            "1.1.1.1",
            "localhost"
        ]
    }

    routing_json = json.dumps(routing, indent=2)
    dns_json = json.dumps(dns, indent=2)

    # Indent block cleanly
    routing_indented = "  " + "\n  ".join(f'"routing": {routing_json}'.splitlines())
    dns_indented = "  " + "\n  ".join(f'"dns": {dns_json}'.splitlines())

    return f"{routing_indented},\n{dns_indented}\n}}"

def patch_xray_config(cfg_path: str = CONFIG_PATH) -> bool:
    if not os.path.exists(cfg_path):
        print(f"[Xray Patcher] File {cfg_path} tidak ditemukan. Dilewati.")
        return True

    with open(cfg_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Check if already clean and working (no dangerous geosite:malware or geosite:torrent, and bittorrent not direct)
    has_bad_rules = "geosite:malware" in content or "geosite:torrent" in content
    has_bittorrent_direct = bool(re.search(r'"outboundTag":\s*"direct"[\s\S]{1,100}"protocol":\s*\[\s*"bittorrent"\s*\]', content))
    has_anti_adblock = "geosite:category-ads-all" in content or "torrent" in content

    if has_anti_adblock and "bittorrent" in content and "IPIfNonMatch" in content and not has_bad_rules and not has_bittorrent_direct:
        print("[Xray Patcher] [OK] Aturan Anti-Adblock & Anti-Torrent sudah terpasang aktif.")
        return True

    print("[Xray Patcher] Memperbarui konfigurasi routing & DNS Xray...")

    # Backup original config
    bak_path = cfg_path + ".bak"
    try:
        shutil.copy2(cfg_path, bak_path)
    except Exception:
        pass

    # Find where "routing": begins
    routing_idx = content.find('"routing"')
    if routing_idx == -1:
        print("[Xray Patcher] [WARN] Blok routing tidak ditemukan dalam config.json.")
        return False

    # Keep everything before "routing": (this preserves inbounds, clients, policy, outbounds, etc.)
    prefix = content[:routing_idx]

    # Generate dynamic routing and dns blocks
    routing_dns_block = generate_routing_and_dns_block(content)
    new_content = prefix + routing_dns_block

    # Validate json without comments
    cleaned = re.sub(r'^\s*#.*$', '', new_content, flags=re.MULTILINE)
    try:
        json.loads(cleaned)
    except Exception as e:
        print(f"[Xray Patcher] [ERROR] Validasi JSON gagal setelah pembaruan: {e}")
        return False

    # Write new content
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    # Test with xray binary
    xray_bin = find_xray_binary()
    if os.path.exists(xray_bin):
        ok, diag = test_xray_config(xray_bin, cfg_path)
        if not ok:
            print(f"[Xray Patcher] [ERROR] Uji konfigurasi Xray gagal:\n{diag}\nMengembalikan backup...")
            if os.path.exists(bak_path):
                shutil.copy2(bak_path, cfg_path)
            return False

    # Restart xray service if systemctl is available
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "restart", "xray"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("[Xray Patcher] [OK] Berhasil! Anti-Adblock & Anti-Torrent aktif di Xray.")
    return True

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else CONFIG_PATH
    ensure_assets()
    ok = patch_xray_config(target)
    sys.exit(0 if ok else 1)

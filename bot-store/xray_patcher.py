#!/usr/bin/env python3
import os
import re
import sys
import json
import shutil
import urllib.request
import subprocess

CONFIG_PATH = "/etc/xray/config.json"
XRAY_BIN = "/usr/local/bin/xray"
ASSET_DIR = "/usr/local/share/xray"

ROUTING_BLOCK = '''  "routing": {
    "domainStrategy": "IPIfNonMatch",
    "rules": [
      {
        "inboundTag": [
          "api"
        ],
        "outboundTag": "api",
        "type": "field"
      },
      {
        "inboundTag": [
          "dnsIn"
        ],
        "outboundTag": "dnsOut",
        "type": "field"
      },
      {
        "type": "field",
        "outboundTag": "blocked",
        "protocol": [
          "bittorrent"
        ]
      },
      {
        "type": "field",
        "outboundTag": "blocked",
        "domain": [
          "geosite:category-ads-all",
          "geosite:malware",
          "torrent",
          "tracker",
          "geosite:torrent"
        ]
      },
      {
        "type": "field",
        "outboundTag": "blocked",
        "ip": [
          "geoip:private"
        ]
      },
      {
        "type": "field",
        "outboundTag": "direct",
        "network": "tcp,udp"
      }
    ]
  },
  "dns": {
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
}'''

def ensure_assets():
    """Ensure geosite.dat and geoip.dat are present for category-ads-all and torrent rules"""
    os.makedirs(ASSET_DIR, exist_ok=True)
    assets = {
        "geosite.dat": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat",
        "geoip.dat": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat"
    }
    for fname, url in assets.items():
        fpath = os.path.join(ASSET_DIR, fname)
        if not os.path.exists(fpath) or os.path.getsize(fpath) < 1000:
            try:
                print(f"[Xray Patcher] Mengunduh aset {fname}...")
                urllib.request.urlretrieve(url, fpath)
                print(f"[Xray Patcher] [OK] {fname} berhasil diunduh.")
            except Exception as e:
                print(f"[Xray Patcher] [WARN] Gagal mengunduh {fname}: {e}")

def patch_xray_config(cfg_path: str = CONFIG_PATH) -> bool:
    if not os.path.exists(cfg_path):
        print(f"[Xray Patcher] File {cfg_path} tidak ditemukan. Dilewati.")
        return True

    with open(cfg_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Check if already has our complete anti-adblock and bittorrent block
    if '"geosite:category-ads-all"' in content and '"bittorrent"' in content and '"IPIfNonMatch"' in content:
        # Check if bittorrent is mistakenly direct
        if not re.search(r'"outboundTag":\s*"direct"[\s\S]{1,100}"protocol":\s*\[\s*"bittorrent"\s*\]', content):
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

    # Combine prefix with new ROUTING_BLOCK
    new_content = prefix + ROUTING_BLOCK

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

    # Test with xray binary if present
    if os.path.exists(XRAY_BIN):
        res = subprocess.run([XRAY_BIN, "run", "-test", "-config", cfg_path], capture_output=True, text=True)
        if res.returncode != 0:
            print(f"[Xray Patcher] [ERROR] Uji konfigurasi Xray gagal: {res.stderr}. Mengembalikan backup...")
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

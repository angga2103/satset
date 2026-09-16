import requests
import json
import logging
from config import load_config

logger = logging.getLogger("pakasir")

BASE_URL = "https://app.pakasir.com/api"

def create_qris(order_id: str, amount: int) -> dict:
    """
    Create a new QRIS payment via Pakasir API.
    Returns dict with success status, qr_url, qr_string, and error message if any.
    """
    cfg = load_config()
    project = cfg.get("PAKASIR_PROJECT_SLUG", "")
    api_key = cfg.get("PAKASIR_API_KEY", "")

    if not project or not api_key:
        return {
            "success": False,
            "error": "Pakasir API credentials (PROJECT_SLUG or API_KEY) belum dikonfigurasi di /etc/satset/bot.env"
        }

    url = f"{BASE_URL}/transactioncreate/qris"
    payload = {
        "project": project,
        "order_id": str(order_id),
        "amount": int(amount),
        "api_key": api_key
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()
        
        # Check standard Pakasir response formats
        is_success = False
        if resp.status_code == 200:
            status_val = str(data.get("status", "")).lower()
            if status_val in ["success", "true", "ok", "completed"] or "data" in data or "qr_string" in data:
                is_success = True

        if is_success:
            inner_data = data.get("data", data)
            qr_url = inner_data.get("qr_url") or inner_data.get("qris_url") or inner_data.get("payment_url") or ""
            qr_string = inner_data.get("qr_string") or inner_data.get("qris_string") or inner_data.get("qr_code") or ""
            total_amount = inner_data.get("total_amount") or inner_data.get("amount") or amount
            expired_at = inner_data.get("expired_at") or inner_data.get("expiry_time") or ""

            return {
                "success": True,
                "order_id": str(order_id),
                "amount": int(total_amount),
                "qr_url": qr_url,
                "qr_string": qr_string,
                "expired_at": expired_at,
                "raw": data
            }
        else:
            err_msg = data.get("message") or data.get("error") or resp.text
            return {
                "success": False,
                "error": f"Pakasir error: {err_msg}"
            }
    except requests.RequestException as e:
        logger.error(f"HTTP request error creating QRIS: {e}")
        return {
            "success": False,
            "error": f"Koneksi ke Pakasir gagal: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Unexpected error creating QRIS: {e}")
        return {
            "success": False,
            "error": f"Gagal membuat QRIS: {str(e)}"
        }

def check_transaction(order_id: str) -> dict:
    """
    Check transaction status from Pakasir API.
    Returns dict with status: 'completed', 'pending', 'expired', 'failed'
    """
    cfg = load_config()
    project = cfg.get("PAKASIR_PROJECT_SLUG", "")
    api_key = cfg.get("PAKASIR_API_KEY", "")

    if not project or not api_key:
        return {
            "status": "error",
            "message": "Pakasir API credentials belum dikonfigurasi."
        }

    url = f"{BASE_URL}/transactiondetail"
    payload = {
        "project": project,
        "order_id": str(order_id),
        "api_key": api_key
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        data = resp.json()

        # Pakasir returns status in data
        inner = data.get("data", data)
        tx_status = str(inner.get("status", "")).lower()

        if tx_status in ["completed", "success", "paid", "lunas", "settlement"]:
            return {
                "status": "completed",
                "order_id": str(order_id),
                "amount": inner.get("amount", 0),
                "raw": data
            }
        elif tx_status in ["pending", "unpaid", "menunggu"]:
            return {
                "status": "pending",
                "order_id": str(order_id),
                "raw": data
            }
        elif tx_status in ["expired", "kadaluarsa"]:
            return {
                "status": "expired",
                "order_id": str(order_id),
                "raw": data
            }
        else:
            return {
                "status": tx_status or "pending",
                "order_id": str(order_id),
                "message": data.get("message", ""),
                "raw": data
            }
    except requests.RequestException as e:
        logger.error(f"HTTP request error checking transaction {order_id}: {e}")
        return {
            "status": "error",
            "message": f"Koneksi gagal: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Unexpected error checking transaction {order_id}: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

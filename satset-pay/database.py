#!/usr/bin/env python3
"""
SATSET-PAY: Database Layer (SQLite WAL Mode)
Manages merchants, invoices, mutations, unique codes, and settings.
"""

import sqlite3
import datetime
import random
import secrets
import json
import logging

logger = logging.getLogger("satset_pay.db")

try:
    import config as _cfg
    if hasattr(_cfg, "DB_FILE"):
        DB_FILE = _cfg.DB_FILE
        INVOICE_TIMEOUT_MINUTES = _cfg.INVOICE_TIMEOUT_MINUTES
        UNIQUE_CODE_MIN = _cfg.UNIQUE_CODE_MIN
        UNIQUE_CODE_MAX = _cfg.UNIQUE_CODE_MAX
    else:
        raise AttributeError("DB_FILE not found in config")
except (ImportError, AttributeError):
    import importlib.util
    import os as _os
    _cfg_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "config.py")
    if _os.path.exists(_cfg_path):
        _spec = importlib.util.spec_from_file_location("satset_pay_cfg_internal", _cfg_path)
        _cfg_mod = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_cfg_mod)
        DB_FILE = _cfg_mod.DB_FILE
        INVOICE_TIMEOUT_MINUTES = _cfg_mod.INVOICE_TIMEOUT_MINUTES
        UNIQUE_CODE_MIN = _cfg_mod.UNIQUE_CODE_MIN
        UNIQUE_CODE_MAX = _cfg_mod.UNIQUE_CODE_MAX
    else:
        DB_FILE = "/etc/satset/satset-pay/satset_pay.db"
        INVOICE_TIMEOUT_MINUTES = 15
        UNIQUE_CODE_MIN = 1
        UNIQUE_CODE_MAX = 999

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except Exception:
        pass
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()

    # 1. Merchants / API Clients
    c.execute("""
    CREATE TABLE IF NOT EXISTS merchants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        api_key TEXT UNIQUE NOT NULL,
        secret_key TEXT NOT NULL,
        webhook_url TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """)

    # 2. Invoices / Payments
    c.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_no TEXT UNIQUE NOT NULL,
        merchant_id INTEGER NOT NULL,
        order_id TEXT NOT NULL,
        amount_original INTEGER NOT NULL,
        unique_code INTEGER NOT NULL,
        amount_total INTEGER NOT NULL,
        qris_string TEXT,
        customer_name TEXT,
        customer_phone TEXT,
        customer_email TEXT,
        status TEXT DEFAULT 'pending',
        callback_url TEXT,
        created_at TEXT NOT NULL,
        expired_at TEXT NOT NULL,
        paid_at TEXT,
        mutation_id INTEGER,
        FOREIGN KEY(merchant_id) REFERENCES merchants(id)
    )
    """)

    # 3. Mutations (Incoming Payments from GoBiz, Shopee, DANA)
    c.execute("""
    CREATE TABLE IF NOT EXISTS mutations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        amount INTEGER NOT NULL,
        raw_text TEXT NOT NULL,
        sender TEXT,
        reference_no TEXT,
        is_matched INTEGER DEFAULT 0,
        matched_invoice_id INTEGER,
        created_at TEXT NOT NULL
    )
    """)

    # 4. Settings
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)

    # Create Indexes for high performance
    c.execute("CREATE INDEX IF NOT EXISTS idx_invoices_status_amount ON invoices(status, amount_total);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_invoices_order_merchant ON invoices(merchant_id, order_id);")
    c.execute("CREATE INDEX IF NOT EXISTS idx_mutations_amount_matched ON mutations(amount, is_matched);")

    # Seed Default Merchant if none exists
    c.execute("SELECT COUNT(*) as count FROM merchants")
    if c.fetchone()["count"] == 0:
        default_api = "sp_live_" + secrets.token_hex(16)
        default_sec = "sp_sec_" + secrets.token_hex(24)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""
        INSERT INTO merchants (name, api_key, secret_key, webhook_url, is_active, created_at)
        VALUES ('Default Merchant (SATSET Store)', ?, ?, '', 1, ?)
        """, (default_api, default_sec, now))

    # Seed Default Settings if missing
    USER_DEFAULT_QRIS = "00020101021126610014COM.GO-JEK.WWW01189360091430357620430210G0357620430303UMI51440014ID.CO.QRIS.WWW0215ID10264816761320303UMI5204481453033605802ID5924Mas Angga Store, Pulsa &6006KEDIRI61056416262070703A01630449CC"
    USER_BRAND_NAME = "Mas Angga Store, Pulsa &"

    defaults = {
        "admin_password": "admin123",
        "static_qris": USER_DEFAULT_QRIS,
        "brand_name": USER_BRAND_NAME,
        "webhook_secret": secrets.token_hex(20),
        "unique_code_min": str(UNIQUE_CODE_MIN),
        "unique_code_max": str(UNIQUE_CODE_MAX),
        "invoice_timeout_minutes": str(INVOICE_TIMEOUT_MINUTES)
    }
    for k, v in defaults.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        if k == "static_qris":
            c.execute("UPDATE settings SET value = ? WHERE key = 'static_qris' AND (value = '' OR value IS NULL)", (v,))
        if k == "brand_name":
            c.execute("UPDATE settings SET value = ? WHERE key = 'brand_name' AND (value = 'SATSET-PAY' OR value = '' OR value IS NULL)", (v,))

    conn.commit()
    conn.close()

# --- Settings Helpers ---

def get_setting(key: str, default: str = "") -> str:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row["value"] if row and row["value"] is not None else default

def set_setting(key: str, value: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings() -> dict:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings")
    rows = c.fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

# --- Merchant Helpers ---

def get_merchant_by_api_key(api_key: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM merchants WHERE api_key = ? AND is_active = 1", (api_key,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_merchant_by_id(merchant_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM merchants WHERE id = ?", (merchant_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_merchants() -> list:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM merchants ORDER BY id ASC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_merchant(name: str, webhook_url: str = "") -> dict:
    api_key = "sp_live_" + secrets.token_hex(16)
    secret_key = "sp_sec_" + secrets.token_hex(24)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO merchants (name, api_key, secret_key, webhook_url, is_active, created_at)
    VALUES (?, ?, ?, ?, 1, ?)
    """, (name, api_key, secret_key, webhook_url, now))
    mid = c.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": mid,
        "name": name,
        "api_key": api_key,
        "secret_key": secret_key,
        "webhook_url": webhook_url,
        "created_at": now
    }

def update_merchant(merchant_id: int, name: str = None, webhook_url: str = None, is_active: int = None):
    conn = get_connection()
    c = conn.cursor()
    updates = []
    params = []
    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if webhook_url is not None:
        updates.append("webhook_url = ?")
        params.append(webhook_url)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(is_active)
    if updates:
        params.append(merchant_id)
        c.execute(f"UPDATE merchants SET {', '.join(updates)} WHERE id = ?", tuple(params))
        conn.commit()
    conn.close()

def delete_merchant(merchant_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM merchants WHERE id = ?", (merchant_id,))
    conn.commit()
    conn.close()

# --- Invoice Helpers ---

def _get_active_unique_codes_for_amount(amount_original: int) -> set:
    """Find currently pending unique codes for the same original amount to avoid collision"""
    conn = get_connection()
    c = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
    SELECT unique_code FROM invoices 
    WHERE amount_original = ? AND status = 'pending' AND expired_at > ?
    """, (amount_original, now_str))
    rows = c.fetchall()
    conn.close()
    return {r["unique_code"] for r in rows}

def create_invoice(
    merchant_id: int,
    order_id: str,
    amount_original: int,
    customer_name: str = "Customer",
    customer_phone: str = "",
    customer_email: str = "",
    callback_url: str = "",
    timeout_minutes: int = None
) -> dict:
    if timeout_minutes is None:
        try:
            timeout_minutes = int(get_setting("invoice_timeout_minutes", str(INVOICE_TIMEOUT_MINUTES)))
        except Exception:
            timeout_minutes = INVOICE_TIMEOUT_MINUTES

    now = datetime.datetime.now()
    created_at = now.strftime("%Y-%m-%d %H:%M:%S")
    expired_at = (now + datetime.timedelta(minutes=timeout_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    # Check if there is an existing pending invoice for this merchant and order_id
    existing = get_invoice_by_merchant_and_order(merchant_id, order_id)
    if existing and existing["status"] == "pending" and existing["expired_at"] > created_at:
        return existing

    # Unique code allocation
    try:
        c_min = int(get_setting("unique_code_min", str(UNIQUE_CODE_MIN)))
        c_max = int(get_setting("unique_code_max", str(UNIQUE_CODE_MAX)))
    except Exception:
        c_min, c_max = UNIQUE_CODE_MIN, UNIQUE_CODE_MAX

    used_codes = _get_active_unique_codes_for_amount(amount_original)
    available = [c for c in range(c_min, c_max + 1) if c not in used_codes]
    if available:
        unique_code = random.choice(available)
    else:
        # Fallback if pool exhausted
        unique_code = random.randint(c_max + 1, c_max + 500)

    amount_total = amount_original + unique_code
    invoice_no = f"INV-{now.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"

    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO invoices (
        invoice_no, merchant_id, order_id, amount_original, unique_code, amount_total,
        customer_name, customer_phone, customer_email, status, callback_url, created_at, expired_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)
    """, (
        invoice_no, merchant_id, order_id, amount_original, unique_code, amount_total,
        customer_name, customer_phone, customer_email, callback_url, created_at, expired_at
    ))
    inv_id = c.lastrowid
    conn.commit()
    conn.close()

    return get_invoice_by_id(inv_id)

def get_invoice_by_id(inv_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT i.*, m.name as merchant_name, m.webhook_url as merchant_webhook, m.secret_key as merchant_secret
    FROM invoices i
    LEFT JOIN merchants m ON i.merchant_id = m.id
    WHERE i.id = ?
    """, (inv_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_invoice_by_no(invoice_no: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT i.*, m.name as merchant_name, m.webhook_url as merchant_webhook, m.secret_key as merchant_secret
    FROM invoices i
    LEFT JOIN merchants m ON i.merchant_id = m.id
    WHERE i.invoice_no = ?
    """, (invoice_no,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_invoice_by_merchant_and_order(merchant_id: int, order_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT i.*, m.name as merchant_name, m.webhook_url as merchant_webhook, m.secret_key as merchant_secret
    FROM invoices i
    LEFT JOIN merchants m ON i.merchant_id = m.id
    WHERE i.merchant_id = ? AND i.order_id = ?
    ORDER BY i.id DESC LIMIT 1
    """, (merchant_id, order_id))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def update_invoice_qris(inv_id: int, qris_string: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE invoices SET qris_string = ? WHERE id = ?", (qris_string, inv_id))
    conn.commit()
    conn.close()

def mark_invoice_completed(inv_id: int, mutation_id: int = None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
    UPDATE invoices
    SET status = 'completed', paid_at = ?, mutation_id = ?
    WHERE id = ? AND status = 'pending'
    """, (now_str, mutation_id, inv_id))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def mark_expired_invoices():
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    UPDATE invoices
    SET status = 'expired'
    WHERE status = 'pending' AND expired_at < ?
    """, (now_str,))
    conn.commit()
    conn.close()

# --- Mutation & Matching Engine ---

def add_mutation(source: str, amount: int, raw_text: str, sender: str = "", reference_no: str = "") -> dict:
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    INSERT INTO mutations (source, amount, raw_text, sender, reference_no, is_matched, created_at)
    VALUES (?, ?, ?, ?, ?, 0, ?)
    """, (source, amount, raw_text, sender, reference_no, now_str))
    mut_id = c.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": mut_id,
        "source": source,
        "amount": amount,
        "raw_text": raw_text,
        "sender": sender,
        "reference_no": reference_no,
        "created_at": now_str
    }

def match_mutation_to_pending_invoice(amount: int, mutation_id: int = None) -> dict:
    """Finds the oldest valid pending invoice matching this total amount and marks it completed"""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    c = conn.cursor()

    # Look for matching pending invoice
    c.execute("""
    SELECT id, invoice_no, order_id, merchant_id, amount_total
    FROM invoices
    WHERE amount_total = ? AND status = 'pending' AND expired_at >= ?
    ORDER BY id ASC
    LIMIT 1
    """, (amount, now_str))
    inv = c.fetchone()

    if not inv:
        conn.close()
        return None

    inv_id = inv["id"]
    # Mark invoice completed
    c.execute("""
    UPDATE invoices
    SET status = 'completed', paid_at = ?, mutation_id = ?
    WHERE id = ?
    """, (now_str, mutation_id, inv_id))

    # Mark mutation matched
    if mutation_id:
        c.execute("""
        UPDATE mutations
        SET is_matched = 1, matched_invoice_id = ?
        WHERE id = ?
        """, (inv_id, mutation_id))

    conn.commit()
    conn.close()

    logger.info(f"Matched mutation Rp {amount:,} to invoice {inv['invoice_no']} (Order: {inv['order_id']})")
    return get_invoice_by_id(inv_id)

# --- Statistics & Dashboard Queries ---

def get_dashboard_stats() -> dict:
    conn = get_connection()
    c = conn.cursor()
    today_start = datetime.datetime.now().strftime("%Y-%m-%d 00:00:00")
    month_start = datetime.datetime.now().strftime("%Y-%m-01 00:00:00")

    # 1. Total revenue today
    c.execute("SELECT SUM(amount_total) as val FROM invoices WHERE status = 'completed' AND paid_at >= ?", (today_start,))
    row = c.fetchone()
    revenue_today = row["val"] or 0

    # 2. Total revenue month
    c.execute("SELECT SUM(amount_total) as val FROM invoices WHERE status = 'completed' AND paid_at >= ?", (month_start,))
    row = c.fetchone()
    revenue_month = row["val"] or 0

    # 3. Total revenue all time
    c.execute("SELECT SUM(amount_total) as val FROM invoices WHERE status = 'completed'")
    row = c.fetchone()
    revenue_all = row["val"] or 0

    # 4. Count invoices by status
    c.execute("SELECT status, COUNT(*) as count FROM invoices GROUP BY status")
    status_counts = {"pending": 0, "completed": 0, "expired": 0}
    for r in c.fetchall():
        status_counts[r["status"]] = r["count"]

    # 5. Count total mutations
    c.execute("SELECT COUNT(*) as count FROM mutations")
    total_mutations = c.fetchone()["count"]

    # 6. Count active merchants
    c.execute("SELECT COUNT(*) as count FROM merchants WHERE is_active = 1")
    total_merchants = c.fetchone()["count"]

    conn.close()
    return {
        "revenue_today": revenue_today,
        "revenue_month": revenue_month,
        "revenue_all": revenue_all,
        "invoices_pending": status_counts.get("pending", 0),
        "invoices_completed": status_counts.get("completed", 0),
        "invoices_expired": status_counts.get("expired", 0),
        "total_invoices": sum(status_counts.values()),
        "total_mutations": total_mutations,
        "total_merchants": total_merchants
    }

def get_recent_invoices(limit: int = 20) -> list:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT i.*, m.name as merchant_name
    FROM invoices i
    LEFT JOIN merchants m ON i.merchant_id = m.id
    ORDER BY i.id DESC
    LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_recent_mutations(limit: int = 20) -> list:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
    SELECT m.*, i.invoice_no, i.order_id
    FROM mutations m
    LEFT JOIN invoices i ON m.matched_invoice_id = i.id
    ORDER BY m.id DESC
    LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# Initialize tables when imported
init_db()

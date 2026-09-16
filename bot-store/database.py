import sqlite3
import os
import datetime

DB_PATH = "/etc/satset/store.db"
LOCAL_DB = os.path.join(os.path.dirname(__file__), "store.db")

def get_db_file():
    if os.path.exists("/etc/satset"):
        return DB_PATH
    return LOCAL_DB

def get_connection():
    db_file = get_db_file()
    db_dir = os.path.dirname(db_file)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_file, check_same_thread=False, timeout=30.0)
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
    
    # Table: Users
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance INTEGER DEFAULT 0,
        created_at TEXT,
        is_admin INTEGER DEFAULT 0
    )
    """)
    
    # Table: Transactions
    c.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        order_id TEXT PRIMARY KEY,
        user_id INTEGER,
        amount INTEGER,
        payment_method TEXT DEFAULT 'qris',
        qris_url TEXT,
        qris_string TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT,
        completed_at TEXT
    )
    """)
    
    # Table: VPN Accounts
    c.execute("""
    CREATE TABLE IF NOT EXISTS vpn_accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        protocol TEXT,
        vpn_username TEXT UNIQUE,
        uuid TEXT,
        plan_type TEXT,
        exp_date TEXT,
        config_link TEXT,
        status TEXT DEFAULT 'active',
        quota_gb INTEGER DEFAULT 350,
        ip_limit INTEGER DEFAULT 1,
        locked_until TEXT,
        lock_reason TEXT,
        created_at TEXT
    )
    """)

    # Safe column migrations for existing databases
    for col, col_def in [
        ("quota_gb", "INTEGER DEFAULT 350"),
        ("ip_limit", "INTEGER DEFAULT 1"),
        ("locked_until", "TEXT"),
        ("lock_reason", "TEXT"),
        ("price_paid", "INTEGER DEFAULT 0")
    ]:
        try:
            c.execute(f"ALTER TABLE vpn_accounts ADD COLUMN {col} {col_def}")
        except Exception:
            pass
            
    # Fix existing PAYG accounts: exp_date must be 'PAYG' rather than fixed date
    try:
        c.execute("UPDATE vpn_accounts SET exp_date = 'PAYG' WHERE plan_type = 'payg' AND (exp_date != 'PAYG' OR exp_date IS NULL)")
    except Exception:
        pass
    
    # Table: Pay-As-You-Go Subscriptions
    c.execute("""
    CREATE TABLE IF NOT EXISTS payg_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        vpn_username TEXT UNIQUE,
        protocol TEXT,
        model TEXT,
        quota_total INTEGER DEFAULT 0,
        quota_used INTEGER DEFAULT 0,
        last_deducted_date TEXT,
        status TEXT DEFAULT 'active'
    )
    """)
    
    conn.commit()
    conn.close()

    # Harden database file permissions (owner read/write only)
    db_file = get_db_file()
    if os.path.exists(db_file) and os.name != "nt":
        try:
            os.chmod(db_file, 0o600)
        except Exception:
            pass

def get_or_create_user(user_id: int, username: str, first_name: str, admin_id=None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_admin = 1 if (admin_id and str(user_id) == str(admin_id)) else 0
    
    if not row:
        c.execute("""
        INSERT INTO users (user_id, username, first_name, balance, created_at, is_admin)
        VALUES (?, ?, ?, 0, ?, ?)
        """, (user_id, username or "", first_name or "", now, is_admin))
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = c.fetchone()
    else:
        # Update is_admin if matches admin_id
        if is_admin and not row["is_admin"]:
            c.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            
    conn.close()
    return dict(row)

def get_user(user_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_users():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, balance FROM users")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_balance(user_id: int) -> int:
    u = get_user(user_id)
    return u["balance"] if u else 0

def add_balance(user_id: int, amount: int) -> int:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res["balance"] if res else 0

def deduct_balance(user_id: int, amount: int) -> bool:
    if amount <= 0:
        return False
    conn = get_connection()
    c = conn.cursor()
    # Atomic conditional update prevents double-spending race conditions
    c.execute(
        "UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
        (amount, user_id, amount)
    )
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def create_transaction(order_id: str, user_id: int, amount: int, qris_url: str = "", qris_string: str = ""):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
    INSERT INTO transactions (order_id, user_id, amount, payment_method, qris_url, qris_string, status, created_at)
    VALUES (?, ?, ?, 'qris', ?, ?, 'pending', ?)
    """, (order_id, user_id, amount, qris_url, qris_string, now))
    conn.commit()
    conn.close()

def get_transaction(order_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM transactions WHERE order_id = ?", (order_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_pending_transactions():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM transactions WHERE status = 'pending'")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def complete_transaction(order_id: str):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Atomic transition from 'pending' to 'completed': exactly one concurrent caller can succeed
    c.execute(
        "UPDATE transactions SET status = 'completed', completed_at = ? WHERE order_id = ? AND status = 'pending'",
        (now, order_id)
    )
    if c.rowcount == 0:
        conn.commit()
        conn.close()
        return None

    c.execute("SELECT * FROM transactions WHERE order_id = ?", (order_id,))
    tx = c.fetchone()
    if tx:
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (tx["amount"], tx["user_id"]))
    conn.commit()
    conn.close()
    return dict(tx) if tx else None

def add_vpn_account(user_id: int, protocol: str, vpn_username: str, uuid: str, plan_type: str, exp_date: str, config_link: str, quota_gb: int = 350, ip_limit: int = 1, price_paid: int = 0):
    conn = get_connection()
    c = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
    INSERT INTO vpn_accounts (user_id, protocol, vpn_username, uuid, plan_type, exp_date, config_link, status, quota_gb, ip_limit, price_paid, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
    """, (user_id, protocol, vpn_username, uuid, plan_type, exp_date, config_link, quota_gb, ip_limit, price_paid, now))
    conn.commit()
    conn.close()

def get_user_vpn_accounts(user_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM vpn_accounts WHERE user_id = ? ORDER BY id DESC", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def has_used_trial(user_id: int) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM vpn_accounts WHERE user_id = ? AND plan_type = 'trial'", (user_id,))
    row = c.fetchone()
    conn.close()
    return row is not None

def add_payg_subscription(user_id: int, vpn_username: str, protocol: str, model: str = "daily", quota_total: int = 0):
    conn = get_connection()
    c = conn.cursor()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    c.execute("""
    INSERT OR REPLACE INTO payg_subscriptions (user_id, vpn_username, protocol, model, quota_total, quota_used, last_deducted_date, status)
    VALUES (?, ?, ?, ?, ?, 0, ?, 'active')
    """, (user_id, vpn_username, protocol, model, quota_total, today))
    conn.commit()
    conn.close()

def get_active_payg_daily_subscriptions():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM payg_subscriptions WHERE model = 'daily' AND status = 'active'")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_payg_deduction(sub_id: int, date_str: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE payg_subscriptions SET last_deducted_date = ? WHERE id = ?", (date_str, sub_id))
    conn.commit()
    conn.close()

def set_payg_status(sub_id: int, status: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE payg_subscriptions SET status = ? WHERE id = ?", (status, sub_id))
    conn.commit()
    conn.close()

def get_total_stats():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as total_users FROM users")
    users = c.fetchone()["total_users"]
    
    c.execute("SELECT COUNT(*) as total_accounts FROM vpn_accounts")
    accounts = c.fetchone()["total_accounts"]
    
    c.execute("SELECT SUM(amount) as total_revenue FROM transactions WHERE status = 'completed'")
    rev_row = c.fetchone()
    revenue = rev_row["total_revenue"] if rev_row and rev_row["total_revenue"] else 0
    
    conn.close()
    return {
        "users": users,
        "accounts": accounts,
        "revenue": revenue
    }

def get_account_by_username(vpn_username: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT v.*, u.username as tg_username, u.first_name as tg_first_name, u.balance
        FROM vpn_accounts v
        LEFT JOIN users u ON v.user_id = u.user_id
        WHERE v.vpn_username = ?
    """, (vpn_username,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def update_account_rules(vpn_username: str, quota_gb: int = None, ip_limit: int = None):
    conn = get_connection()
    c = conn.cursor()
    if quota_gb is not None:
        c.execute("UPDATE vpn_accounts SET quota_gb = ? WHERE vpn_username = ?", (quota_gb, vpn_username))
    if ip_limit is not None:
        c.execute("UPDATE vpn_accounts SET ip_limit = ? WHERE vpn_username = ?", (ip_limit, vpn_username))
    conn.commit()
    conn.close()

def lock_account_db(vpn_username: str, duration_minutes: int = 10, reason: str = "multi_login"):
    conn = get_connection()
    c = conn.cursor()
    locked_until = (datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)).strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        UPDATE vpn_accounts 
        SET status = 'suspended', locked_until = ?, lock_reason = ? 
        WHERE vpn_username = ?
    """, (locked_until, reason, vpn_username))
    conn.commit()
    conn.close()
    return locked_until

def unlock_account_db(vpn_username: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        UPDATE vpn_accounts 
        SET status = 'active', locked_until = NULL, lock_reason = NULL 
        WHERE vpn_username = ?
    """, (vpn_username,))
    conn.commit()
    conn.close()

def get_locked_accounts():
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT v.*, u.username as tg_username, u.first_name as tg_first_name
        FROM vpn_accounts v
        LEFT JOIN users u ON v.user_id = u.user_id
        WHERE v.status = 'suspended'
    """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_vpn_accounts_detailed(limit: int = 100):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT v.*, u.username as tg_username, u.first_name as tg_first_name, u.balance
        FROM vpn_accounts v
        LEFT JOIN users u ON v.user_id = u.user_id
        ORDER BY v.id DESC
        LIMIT ?
    """, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_vpn_account_by_id(acc_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT v.*, u.username as tg_username, u.first_name as tg_first_name, u.balance
        FROM vpn_accounts v
        LEFT JOIN users u ON v.user_id = u.user_id
        WHERE v.id = ?
    """, (acc_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def cancel_payg_subscription(vpn_username: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE payg_subscriptions SET status = 'cancelled' WHERE vpn_username = ?", (vpn_username,))
    conn.commit()
    conn.close()

def record_refund_transaction(user_id: int, amount: int, description: str = "refund"):
    conn = get_connection()
    c = conn.cursor()
    order_id = f"REF-{int(datetime.datetime.now().timestamp())}-{user_id}"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
    INSERT INTO transactions (order_id, user_id, amount, payment_method, status, created_at, completed_at)
    VALUES (?, ?, ?, ?, 'completed', ?, ?)
    """, (order_id, user_id, amount, description, now, now))
    conn.commit()
    conn.close()
    return order_id

def delete_vpn_account_by_username(vpn_username: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM vpn_accounts WHERE vpn_username = ?", (vpn_username,))
    c.execute("DELETE FROM payg_subscriptions WHERE vpn_username = ?", (vpn_username,))
    conn.commit()
    conn.close()

# Initialize tables when imported
init_db()


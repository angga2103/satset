#!/usr/bin/env python3
"""
SATSET-PAY: Main Application Entrypoint
Flask-powered REST API Gateway, Webhook Listener, Admin Dashboard, and Public Checkout.
"""

import os
import sys
import json
import time
import hmac
import hashlib
import logging
import threading
import urllib.request
import urllib.error
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, render_template, redirect, url_for, session, abort

from config import (
    SERVER_HOST, SERVER_PORT, SECRET_KEY, DEFAULT_ADMIN_USER,
    DEFAULT_ADMIN_PASS, VERSION
)
import database
import qris_engine
from parsers import parse_incoming_notification

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("satset_pay")

app = Flask(__name__)
app.secret_key = SECRET_KEY

# --- Background Worker ---
def background_cleanup_and_expiry():
    """Runs periodically to mark expired invoices"""
    while True:
        try:
            database.mark_expired_invoices()
        except Exception as e:
            logger.error(f"Error in background expiry cleaner: {e}")
        time.sleep(30)

threading.Thread(target=background_cleanup_and_expiry, daemon=True).start()

# --- Helper: Webhook Dispatcher to Merchant ---
def dispatch_merchant_webhook(invoice: dict):
    """Sends webhook callback to merchant callback_url in background thread"""
    def _send():
        callback_url = invoice.get("callback_url") or invoice.get("merchant_webhook")
        if not callback_url:
            return

        secret_key = invoice.get("merchant_secret") or "satset_secret"
        payload = {
            "event": "payment.completed",
            "invoice_no": invoice["invoice_no"],
            "order_id": invoice["order_id"],
            "amount_original": invoice["amount_original"],
            "amount_total": invoice["amount_total"],
            "status": "completed",
            "paid_at": invoice.get("paid_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "timestamp": int(time.time())
        }

        body_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        signature = hmac.new(secret_key.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "SATSET-PAY-Webhook/1.0",
            "X-Callback-Signature": signature
        }

        for attempt in range(3):
            try:
                req = urllib.request.Request(callback_url, data=body_bytes, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    if resp.status in [200, 201, 204]:
                        logger.info(f"Webhook dispatched successfully to {callback_url} for order {invoice['order_id']}")
                        return
            except Exception as e:
                logger.warning(f"Webhook attempt {attempt+1} failed for {callback_url}: {e}")
                time.sleep(2)

    threading.Thread(target=_send, daemon=True).start()

# --- Authentication Decorators ---
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated_function

def get_auth_merchant():
    """Extracts merchant from X-API-Key or Authorization header"""
    api_key = request.headers.get("X-API-Key", "").strip()
    if not api_key:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            api_key = auth.split(" ", 1)[1].strip()
    if not api_key:
        return None
    return database.get_merchant_by_api_key(api_key)

# =========================================================================
# 1. PUBLIC CHECKOUT & INVOICE STATUS
# =========================================================================

@app.route("/pay/<invoice_no>")
def public_checkout(invoice_no):
    inv = database.get_invoice_by_no(invoice_no)
    if not inv:
        abort(404, description="Invoice tidak ditemukan")

    # Check if expired
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if inv["status"] == "pending" and inv["expired_at"] < now_str:
        database.mark_invoice_completed(inv["id"]) # mark expired if needed
        inv["status"] = "expired"

    # Generate Dynamic QRIS if needed
    static_qris = database.get_setting("static_qris", "")
    qris_string = inv.get("qris_string")

    if not qris_string and static_qris:
        try:
            qris_string = qris_engine.make_dynamic_qris(static_qris, inv["amount_total"])
            database.update_invoice_qris(inv["id"], qris_string)
        except Exception as e:
            logger.warning(f"Failed to generate dynamic QRIS: {e}")
            qris_string = static_qris

    content_to_qr = qris_string or f"PAY:{inv['invoice_no']}:{inv['amount_total']}"
    qr_data_uri = qris_engine.generate_qr_data_uri(content_to_qr)

    brand_name = database.get_setting("brand_name", "SATSET-PAY")
    return render_template(
        "checkout.html",
        invoice=inv,
        qr_data_uri=qr_data_uri,
        brand_name=brand_name
    )

@app.route("/api/v1/invoice/<invoice_no>/status")
def public_invoice_status(invoice_no):
    inv = database.get_invoice_by_no(invoice_no)
    if not inv:
        return jsonify({"status": "not_found"}), 404

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if inv["status"] == "pending" and inv["expired_at"] < now_str:
        inv["status"] = "expired"

    return jsonify({
        "status": inv["status"],
        "invoice_no": inv["invoice_no"],
        "order_id": inv["order_id"],
        "amount_total": inv["amount_total"],
        "paid_at": inv.get("paid_at")
    })

# =========================================================================
# 2. MERCHANT REST API
# =========================================================================

@app.route("/api/v1/order/create", methods=["POST"])
def api_create_order():
    merchant = get_auth_merchant()
    if not merchant:
        return jsonify({"status": "error", "message": "Unauthorized: Invalid or missing API Key"}), 401

    data = request.get_json(silent=True) or {}
    order_id = str(data.get("order_id", "")).strip()
    amount_raw = data.get("amount")

    if not order_id:
        return jsonify({"status": "error", "message": "Parameter 'order_id' wajib diisi"}), 400

    try:
        amount_original = int(amount_raw)
        if amount_original < 100:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "Parameter 'amount' harus berupa angka minimal 100"}), 400

    customer_name = data.get("customer_name", "Customer")
    customer_phone = data.get("customer_phone", "")
    customer_email = data.get("customer_email", "")
    callback_url = data.get("callback_url") or merchant.get("webhook_url", "")

    invoice = database.create_invoice(
        merchant_id=merchant["id"],
        order_id=order_id,
        amount_original=amount_original,
        customer_name=customer_name,
        customer_phone=customer_phone,
        customer_email=customer_email,
        callback_url=callback_url
    )

    # Dynamic QRIS Generation
    static_qris = database.get_setting("static_qris", "")
    qris_string = ""
    if static_qris:
        try:
            qris_string = qris_engine.make_dynamic_qris(static_qris, invoice["amount_total"])
            database.update_invoice_qris(invoice["id"], qris_string)
        except Exception as e:
            logger.warning(f"Failed to generate dynamic QRIS: {e}")
            qris_string = static_qris

    host_header = request.host
    checkout_url = f"http://{host_header}/pay/{invoice['invoice_no']}"

    return jsonify({
        "status": "success",
        "invoice_no": invoice["invoice_no"],
        "order_id": invoice["order_id"],
        "amount_original": invoice["amount_original"],
        "unique_code": invoice["unique_code"],
        "amount_total": invoice["amount_total"],
        "checkout_url": checkout_url,
        "qris_string": qris_string,
        "created_at": invoice["created_at"],
        "expired_at": invoice["expired_at"]
    }), 201

@app.route("/api/v1/order/<order_id>", methods=["GET"])
def api_get_order(order_id):
    merchant = get_auth_merchant()
    if not merchant:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    inv = database.get_invoice_by_merchant_and_order(merchant["id"], order_id)
    if not inv:
        return jsonify({"status": "error", "message": "Pesanan tidak ditemukan"}), 404

    return jsonify({
        "status": "success",
        "order": {
            "invoice_no": inv["invoice_no"],
            "order_id": inv["order_id"],
            "amount_original": inv["amount_original"],
            "unique_code": inv["unique_code"],
            "amount_total": inv["amount_total"],
            "payment_status": inv["status"],
            "created_at": inv["created_at"],
            "expired_at": inv["expired_at"],
            "paid_at": inv.get("paid_at")
        }
    })

# =========================================================================
# 3. ANDROID NOTIFICATION LISTENER WEBHOOK
# =========================================================================

@app.route("/api/v1/webhook/listener", methods=["POST"])
def webhook_listener():
    # Verify Webhook Secret
    expected_secret = database.get_setting("webhook_secret", "").strip()
    req_secret = (request.headers.get("X-Webhook-Secret") or request.args.get("secret") or "").strip()

    data = request.get_json(silent=True) or {}
    logger.info(f"Webhook incoming from {request.remote_addr}: {data}")

    if not req_secret and isinstance(data, dict):
        req_secret = str(data.get("secret", "")).strip()

    if expected_secret and req_secret != expected_secret:
        logger.warning(f"Webhook rejected: secret mismatch from {request.remote_addr}")
        return jsonify({"status": "error", "message": "Invalid webhook secret"}), 401

    title = data.get("title", "")
    body = data.get("body", "")
    package = data.get("package", "")

    parsed = parse_incoming_notification(title, body, package)
    if not parsed.get("is_valid") or parsed.get("amount", 0) <= 0:
        return jsonify({
            "status": "ignored",
            "message": "Not a payment notification or amount could not be detected",
            "parsed": parsed
        }), 200

    amount = parsed["amount"]
    source = parsed["source"]
    sender = parsed.get("sender", "")
    ref_no = parsed.get("reference_no", "")
    raw_text = parsed.get("raw_text", "")

    # Save to mutations table
    mutation = database.add_mutation(
        source=source,
        amount=amount,
        raw_text=raw_text,
        sender=sender,
        reference_no=ref_no
    )

    # Match to pending invoice
    matched_invoice = database.match_mutation_to_pending_invoice(amount, mutation["id"])

    if matched_invoice:
        # Dispatch webhook callback to merchant in background
        dispatch_merchant_webhook(matched_invoice)

        return jsonify({
            "status": "success",
            "matched": True,
            "invoice_no": matched_invoice["invoice_no"],
            "order_id": matched_invoice["order_id"],
            "amount": amount,
            "source": source
        }), 200
    else:
        return jsonify({
            "status": "success",
            "matched": False,
            "message": f"Mutation of Rp {amount:,} saved, but no matching pending invoice found.",
            "mutation_id": mutation["id"]
        }), 200

# =========================================================================
# 4. ADMIN DASHBOARD & CONTROLS
# =========================================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        user = request.form.get("username", "").strip()
        pwd = request.form.get("password", "").strip()

        stored_user = database.get_setting("admin_username", DEFAULT_ADMIN_USER)
        stored_pass = database.get_setting("admin_password", DEFAULT_ADMIN_PASS)

        if user == stored_user and pwd == stored_pass:
            session["is_admin"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("login.html", error="Username atau Password salah!")

    return render_template("login.html")

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = database.get_dashboard_stats()
    invoices = database.get_recent_invoices(25)
    mutations = database.get_recent_mutations(25)
    merchants = database.get_all_merchants()
    settings = database.get_all_settings()

    return render_template(
        "dashboard.html",
        stats=stats,
        invoices=invoices,
        mutations=mutations,
        merchants=merchants,
        settings=settings,
        request_host=request.host.split(":")[0]
    )

@app.route("/admin/merchants/create", methods=["POST"])
@admin_required
def admin_create_merchant():
    name = request.form.get("name", "").strip()
    webhook_url = request.form.get("webhook_url", "").strip()
    if name:
        database.create_merchant(name, webhook_url)
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/settings/save", methods=["POST"])
@admin_required
def admin_save_settings():
    static_qris = request.form.get("static_qris", "").strip()
    timeout = request.form.get("invoice_timeout_minutes", "10").strip()
    c_min = request.form.get("unique_code_min", "1").strip()
    c_max = request.form.get("unique_code_max", "499").strip()
    webhook_secret = request.form.get("webhook_secret", "").strip()

    database.set_setting("static_qris", static_qris)
    database.set_setting("invoice_timeout_minutes", timeout)
    database.set_setting("unique_code_min", c_min)
    database.set_setting("unique_code_max", c_max)
    database.set_setting("webhook_secret", webhook_secret)

    return redirect(url_for("admin_dashboard"))

@app.route("/admin/simulator/trigger", methods=["POST"])
@admin_required
def admin_simulator():
    source = request.form.get("source", "gobiz")
    amount = int(request.form.get("amount", 0))
    sender = request.form.get("sender", "Tester")

    raw_text = f"Simulasi transfer masuk Rp {amount:,} dari {sender} via {source}"
    mut = database.add_mutation(source, amount, raw_text, sender)
    matched = database.match_mutation_to_pending_invoice(amount, mut["id"])
    if matched:
        dispatch_merchant_webhook(matched)

    return redirect(url_for("admin_dashboard"))

@app.route("/")
def index():
    return redirect(url_for("admin_dashboard"))

if __name__ == "__main__":
    logger.info(f"Starting SATSET-PAY Gateway v{VERSION} on {SERVER_HOST}:{SERVER_PORT}")
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=False)

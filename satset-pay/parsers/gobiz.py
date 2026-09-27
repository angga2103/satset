#!/usr/bin/env python3
"""
GoBiz (GoPay Merchant) Notification Parser
Handles push notifications from GoBiz app.
"""

import re

def parse_gobiz_notification(title: str, body: str) -> dict:
    raw = f"{title} | {body}".strip()
    full_text = f"{title} {body}".strip()

    # Pattern 1: "Penerimaan GoPay: Rp 10.234 berhasil diterima dari Budi Santoso"
    # Pattern 2: "Kamu menerima pembayaran GoPay sebesar Rp 25.000 dari..."
    # Pattern 3: "Transaksi baru GoPay Rp 50.000 berhasil"
    
    amount = 0
    sender = ""
    ref_no = ""

    # Match amount
    m_amount = re.search(r"(?:gopay:?\s*rp|sebesar\s*rp|rp\.?)\s*([0-9.,]+)", full_text, re.IGNORECASE)
    if m_amount:
        raw_amt = m_amount.group(1).replace(".", "").replace(",", "")
        digits = re.sub(r"[^\d]", "", raw_amt)
        amount = int(digits) if digits else 0

    # Match sender
    m_sender = re.search(r"(?:dari|pengirim)\s+([^.,\n\r]+)", full_text, re.IGNORECASE)
    if m_sender:
        sender = m_sender.group(1).strip()

    # Match reference number if any
    m_ref = re.search(r"(?:order id|ref|no|id:?)\s*([a-zA-Z0-9_\-]+)", full_text, re.IGNORECASE)
    if m_ref:
        ref_no = m_ref.group(1).strip()

    is_valid = (amount > 0)
    return {
        "source": "gobiz",
        "amount": amount,
        "sender": sender,
        "reference_no": ref_no,
        "is_valid": is_valid,
        "raw_text": raw
    }

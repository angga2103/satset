#!/usr/bin/env python3
"""
DANA Bisnis / DANA Notification Parser
Handles push notifications from DANA or DANA Bisnis app.
"""

import re

def parse_dana_notification(title: str, body: str) -> dict:
    raw = f"{title} | {body}".strip()
    full_text = f"{title} {body}".strip()

    # Pattern 1: "Berhasil menerima pembayaran QRIS sebesar Rp 15.234 dari Budi"
    # Pattern 2: "Kamu menerima uang sebesar Rp 10.000 dari Ahmad"
    # Pattern 3: "Penerimaan DANA Bisnis Rp 50.120 berhasil"
    # Pattern 4: "Transfer masuk Rp 25.000 dari..."

    amount = 0
    sender = "DANA User"
    ref_no = ""

    # Match amount
    m_amount = re.search(r"(?:sebesar\s*rp|bisnis\s*rp|masuk\s*rp|rp\.?)\s*([0-9.,]+)", full_text, re.IGNORECASE)
    if m_amount:
        raw_amt = m_amount.group(1).replace(".", "").replace(",", "")
        digits = re.sub(r"[^\d]", "", raw_amt)
        amount = int(digits) if digits else 0

    # Match sender
    m_sender = re.search(r"(?:dari|pengirim)\s+([^.,\n\r]+)", full_text, re.IGNORECASE)
    if m_sender:
        sender = m_sender.group(1).strip()

    is_valid = (amount > 0)
    return {
        "source": "dana",
        "amount": amount,
        "sender": sender,
        "reference_no": ref_no,
        "is_valid": is_valid,
        "raw_text": raw
    }

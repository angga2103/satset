#!/usr/bin/env python3
"""
Shopee Partner (ShopeePay / QRIS) Notification Parser
Handles push notifications from Shopee Partner app.
"""

import re

def parse_shopee_notification(title: str, body: str) -> dict:
    raw = f"{title} | {body}".strip()
    full_text = f"{title} {body}".strip()

    # Pattern 1: "Pembayaran sebesar Rp 15.234 berhasil diterima dari ShopeePay"
    # Pattern 2: "Penerimaan dana Rp 10.000 dari ShopeePay/QRIS berhasil"
    # Pattern 3: "Transaksi Masuk: Rp 12.500 dari pengguna Shopee"

    amount = 0
    sender = "ShopeePay"
    ref_no = ""

    # Match amount
    m_amount = re.search(r"(?:sebesar\s*rp|dana\s*rp|masuk:?\s*rp|rp\.?)\s*([0-9.,]+)", full_text, re.IGNORECASE)
    if m_amount:
        raw_amt = m_amount.group(1).replace(".", "").replace(",", "")
        digits = re.sub(r"[^\d]", "", raw_amt)
        amount = int(digits) if digits else 0

    # Match sender
    m_sender = re.search(r"(?:dari|pengguna)\s+([^.,\n\r]+)", full_text, re.IGNORECASE)
    if m_sender:
        sender = m_sender.group(1).strip()

    is_valid = (amount > 0)
    return {
        "source": "shopee",
        "amount": amount,
        "sender": sender,
        "reference_no": ref_no,
        "is_valid": is_valid,
        "raw_text": raw
    }

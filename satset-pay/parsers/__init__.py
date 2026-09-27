#!/usr/bin/env python3
"""
SATSET-PAY: Notification Parsers
Extracts transaction amounts, sender names, and reference numbers
from Android push notifications (GoBiz, Shopee Partner, DANA Bisnis).
"""

import re
from .gobiz import parse_gobiz_notification
from .shopee import parse_shopee_notification
from .dana import parse_dana_notification

def clean_amount(amount_str: str) -> int:
    """Sanitizes indonesian currency formatting (e.g. 10.000,00 or 10,000 or 10.000) to int"""
    if not amount_str:
        return 0
    # Remove dots and commas
    cleaned = amount_str.strip().replace("Rp", "").replace("RP", "").replace("rp", "").strip()
    
    # Handle decimals if present (e.g. 10.000,00 -> 10000)
    if "," in cleaned and len(cleaned.split(",")[-1]) == 2:
        cleaned = cleaned.split(",")[0]
    elif "." in cleaned and len(cleaned.split(".")[-1]) == 2 and len(cleaned.split(".")) > 1:
        # e.g. 10000.00
        cleaned = cleaned.split(".")[0]

    # Remove all non-digits
    digits = re.sub(r"[^\d]", "", cleaned)
    return int(digits) if digits else 0

def parse_incoming_notification(title: str = "", body: str = "", package_name: str = "") -> dict:
    """
    Auto-detects provider and extracts payment mutation details.
    Returns:
    {
        "source": "gobiz" | "shopee" | "dana" | "unknown",
        "amount": int,
        "sender": str,
        "reference_no": str,
        "is_valid": bool,
        "raw_text": str
    }
    """
    raw_combined = f"{title} | {body}".strip()
    pkg = package_name.lower().strip()
    text = (title + " " + body).lower()

    # 1. Package Name / Keyword Routing
    if "gobiz" in pkg or "gopay" in pkg or "gobiz" in text or "gopay" in text:
        res = parse_gobiz_notification(title, body)
        if res.get("is_valid"):
            return res

    if "shopee" in pkg or "shopeepartner" in text or "shopeepay" in text:
        res = parse_shopee_notification(title, body)
        if res.get("is_valid"):
            return res

    if "dana" in pkg or "dana bisnis" in text or "id.dana" in pkg or "dana" in text:
        res = parse_dana_notification(title, body)
        if res.get("is_valid"):
            return res

    # 2. Heuristic fallback testing across all parsers
    for parser_func in [parse_gobiz_notification, parse_shopee_notification, parse_dana_notification]:
        res = parser_func(title, body)
        if res.get("is_valid") and res.get("amount", 0) > 0:
            return res

    # 3. Universal regex fallback for any generic bank/e-wallet notification
    # Looks for "Rp 10.000" or "Rp10,000"
    m_amount = re.search(r"(?:rp\.?|idr\.?)\s*([0-9.,]+)", text, re.IGNORECASE)
    if m_amount:
        amt = clean_amount(m_amount.group(1))
        if amt > 0:
            return {
                "source": "generic",
                "amount": amt,
                "sender": "",
                "reference_no": "",
                "is_valid": True,
                "raw_text": raw_combined
            }

    return {
        "source": "unknown",
        "amount": 0,
        "sender": "",
        "reference_no": "",
        "is_valid": False,
        "raw_text": raw_combined
    }

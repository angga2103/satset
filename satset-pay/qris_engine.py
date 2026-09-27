#!/usr/bin/env python3
"""
SATSET-PAY: EMVCo QRIS Engine
Converts Static QRIS (GoBiz, Shopee, DANA, BCA) into Dynamic QRIS with exact amount,
computes CRC-16/CCITT checksum, and renders SVG/Data-URI QR codes.
"""

import re
import io
import base64

def calculate_crc16_ccitt(data: str) -> str:
    """
    Computes standard EMVCo CRC-16/CCITT-FALSE checksum.
    Polynomial: 0x1021, Initial: 0xFFFF.
    Returns 4-character uppercase hexadecimal string.
    """
    crc = 0xFFFF
    for b in data.encode("utf-8"):
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return f"{crc:04X}"

def parse_emvco_tags(qris_string: str) -> dict:
    """Parses raw EMVCo TLV (Tag-Length-Value) string into a dictionary"""
    tags = {}
    i = 0
    q_len = len(qris_string)
    while i < q_len - 4:
        tag = qris_string[i:i+2]
        if not tag.isdigit():
            break
        length_str = qris_string[i+2:i+4]
        if not length_str.isdigit():
            break
        val_len = int(length_str)
        value = qris_string[i+4:i+4+val_len]
        tags[tag] = value
        i += 4 + val_len
    return tags

def make_dynamic_qris(static_qris: str, amount: int) -> str:
    """
    Converts a static QRIS string into a dynamic QRIS string with the specified amount.
    1. Changes Tag 01 (Point of Initiation Method) from 11 (Static) to 12 (Dynamic).
    2. Inserts or replaces Tag 54 (Transaction Amount).
    3. Recalculates Tag 63 (CRC-16 Checksum).
    """
    if not static_qris or len(static_qris.strip()) < 30:
        raise ValueError("String QRIS statis tidak valid atau terlalu pendek.")

    raw = static_qris.strip()

    # Step 1: Strip existing CRC-16 tag (Tag 63) from the end if present
    # Format of CRC tag: '6304' followed by 4 hex characters
    crc_match = re.search(r"6304[A-Fa-f0-9]{4}$", raw)
    if crc_match:
        raw_without_crc = raw[:crc_match.start()]
    else:
        # If no standard ending, try stripping any trailing 6304...
        idx_63 = raw.rfind("6304")
        if idx_63 != -1 and idx_63 >= len(raw) - 8:
            raw_without_crc = raw[:idx_63]
        else:
            raw_without_crc = raw

    # Step 2: Convert Tag 01 from 11 (Static) to 12 (Dynamic)
    # Tag 01 format: 010211 -> 010212
    if "010211" in raw_without_crc[:16]:
        raw_without_crc = raw_without_crc.replace("010211", "010212", 1)

    # Step 3: Handle Tag 54 (Transaction Amount)
    amount_str = str(int(amount))
    amount_tag = f"54{len(amount_str):02d}{amount_str}"

    # Check if Tag 54 already exists
    # Tag 54 is followed by 2 digits length
    tag54_match = re.search(r"54(\d{2})(\d+)", raw_without_crc)
    if tag54_match:
        old_tag_len = int(tag54_match.group(1))
        old_full_tag = raw_without_crc[tag54_match.start() : tag54_match.start() + 4 + old_tag_len]
        raw_without_crc = raw_without_crc[:tag54_match.start()] + amount_tag + raw_without_crc[tag54_match.start() + 4 + old_tag_len:]
    else:
        # Insert Tag 54 before Tag 58 (Country code) if Tag 58 exists
        idx_58 = raw_without_crc.find("5802ID")
        if idx_58 != -1:
            raw_without_crc = raw_without_crc[:idx_58] + amount_tag + raw_without_crc[idx_58:]
        else:
            # Fallback: append Tag 54 at the end
            raw_without_crc += amount_tag

    # Step 4: Append '6304' and calculate CRC-16
    payload_to_crc = raw_without_crc + "6304"
    crc_code = calculate_crc16_ccitt(payload_to_crc)

    return payload_to_crc + crc_code

def generate_qr_svg(content: str) -> str:
    """
    Generates an inline SVG QR code using pure Python (with optional qrcode library if present).
    """
    try:
        import qrcode
        import qrcode.image.svg
        factory = qrcode.image.svg.SvgPathImage
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
            image_factory=factory
        )
        qr.add_data(content)
        qr.make(fit=True)
        img = qr.make_image()
        stream = io.BytesIO()
        img.save(stream)
        return stream.getvalue().decode("utf-8")
    except ImportError:
        # Fallback using Google Charts API image URL or QuickChart SVG
        pass

    # High-quality fallback SVG wrapper
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 250 250" width="100%" height="100%">
      <rect width="100%" height="100%" fill="#ffffff"/>
      <image href="https://api.qrserver.com/v1/create-qr-code/?size=250x250&amp;data={content}" width="250" height="250"/>
    </svg>"""

def generate_qr_data_uri(content: str) -> str:
    """
    Generates a PNG base64 Data-URI for <img> tags.
    """
    try:
        import qrcode
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=8,
            border=2
        )
        qr.add_data(content)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64}"
    except ImportError:
        # Fast fallback via reliable QR server
        return f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={content}"

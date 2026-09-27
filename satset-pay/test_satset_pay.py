#!/usr/bin/env python3
"""
SATSET-PAY: Comprehensive Automated Test Suite
Verifies QRIS engine, notification parsers, database operations,
API endpoints, and end-to-end payment matching workflow.
"""

import os
import sys
import unittest
import json

# Ensure satset-pay directory is in path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import config
import database
import qris_engine
import parsers
from app import app

class TestSatsetPay(unittest.TestCase):

    def setUp(self):
        # Configure app for testing
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

    def test_01_qris_crc16_and_dynamic_engine(self):
        # Standard sample static QRIS
        sample_static = "00020101021126600016ID.CO.GOPAY.WWW01189360091800000000000208123456785204541153033605802ID5910TOKO SATSET6007JAKARTA6304ABCD"
        
        # 1. Test CRC-16 calculation
        test_data = "0002010102116304"
        crc = qris_engine.calculate_crc16_ccitt(test_data)
        self.assertEqual(len(crc), 4)
        self.assertTrue(all(c in "0123456789ABCDEF" for c in crc))

        # 2. Test Dynamic QRIS conversion
        amount = 15234
        dynamic = qris_engine.make_dynamic_qris(sample_static, amount)
        self.assertIn("010212", dynamic)  # Dynamic tag
        self.assertIn("540515234", dynamic)  # Tag 54 + length 05 + 15234
        self.assertTrue(dynamic.endswith(qris_engine.calculate_crc16_ccitt(dynamic[:-4])))

        # 3. Test Data URI generation
        data_uri = qris_engine.generate_qr_data_uri("TEST_QRIS")
        self.assertTrue(data_uri.startswith("data:image/png;base64,") or data_uri.startswith("http"))
        print("[PASS] test_01_qris_crc16_and_dynamic_engine")

    def test_02_notification_parsers(self):
        # 1. Test GoBiz
        t_gobiz = "Penerimaan GoPay"
        b_gobiz = "Penerimaan GoPay: Rp 10.147 berhasil diterima dari Budi Santoso"
        res_g = parsers.parse_incoming_notification(t_gobiz, b_gobiz, "com.gojek.merchant")
        self.assertEqual(res_g["source"], "gobiz")
        self.assertEqual(res_g["amount"], 10147)
        self.assertIn("Budi Santoso", res_g["sender"])
        self.assertTrue(res_g["is_valid"])

        # 2. Test Shopee Partner
        t_shopee = "Shopee Partner"
        b_shopee = "Pembayaran sebesar Rp 25.350 berhasil diterima dari ShopeePay"
        res_s = parsers.parse_incoming_notification(t_shopee, b_shopee, "com.shopee.merchant")
        self.assertEqual(res_s["source"], "shopee")
        self.assertEqual(res_s["amount"], 25350)
        self.assertTrue(res_s["is_valid"])

        # 3. Test DANA Bisnis
        t_dana = "DANA Bisnis"
        b_dana = "Berhasil menerima pembayaran QRIS sebesar Rp 50.125 dari Siti Rahma"
        res_d = parsers.parse_incoming_notification(t_dana, b_dana, "id.dana")
        self.assertEqual(res_d["source"], "dana")
        self.assertEqual(res_d["amount"], 50125)
        self.assertIn("Siti Rahma", res_d["sender"])
        self.assertTrue(res_d["is_valid"])

        # 4. Test Non-payment notification ignored
        t_chat = "Pesan Baru"
        b_chat = "Halo apa kabar kak?"
        res_c = parsers.parse_incoming_notification(t_chat, b_chat, "com.whatsapp")
        self.assertFalse(res_c["is_valid"])
        self.assertEqual(res_c["amount"], 0)
        print("[PASS] test_02_notification_parsers")

    def test_03_database_and_matching_engine(self):
        # 1. Create merchant
        merchant = database.create_merchant("Merchant Unit Test")
        self.assertIsNotNone(merchant["api_key"])
        self.assertIsNotNone(merchant["secret_key"])

        # 2. Create invoice
        order_id = "TEST-ORDER-001"
        amount_orig = 10000
        inv = database.create_invoice(
            merchant_id=merchant["id"],
            order_id=order_id,
            amount_original=amount_orig,
            customer_name="Test Buyer"
        )
        self.assertIsNotNone(inv["invoice_no"])
        self.assertEqual(inv["status"], "pending")
        self.assertEqual(inv["amount_original"], amount_orig)
        self.assertGreater(inv["amount_total"], amount_orig)
        total_expected = inv["amount_total"]

        # 3. Add mutation matching total_expected
        mut = database.add_mutation(
            source="gobiz",
            amount=total_expected,
            raw_text=f"Penerimaan GoPay: Rp {total_expected:,} berhasil diterima",
            sender="Test Buyer"
        )
        self.assertEqual(mut["amount"], total_expected)

        # 4. Match mutation
        matched = database.match_mutation_to_pending_invoice(total_expected, mut["id"])
        self.assertIsNotNone(matched)
        self.assertEqual(matched["id"], inv["id"])
        self.assertEqual(matched["status"], "completed")

        # 5. Check stats
        stats = database.get_dashboard_stats()
        self.assertGreaterEqual(stats["invoices_completed"], 1)
        self.assertGreaterEqual(stats["revenue_all"], total_expected)
        print("[PASS] test_03_database_and_matching_engine")

    def test_04_api_create_and_checkout_endpoints(self):
        # 1. Get or create test merchant
        merchants = database.get_all_merchants()
        merchant = merchants[0]
        api_key = merchant["api_key"]

        # 2. Test Unauthorized API create
        resp_unauth = self.client.post("/api/v1/order/create", json={"order_id": "ORD-1", "amount": 20000})
        self.assertEqual(resp_unauth.status_code, 401)

        # 3. Test Authorized API create
        resp_auth = self.client.post(
            "/api/v1/order/create",
            headers={"X-API-Key": api_key},
            json={
                "order_id": f"ORD-AUTO-{os.getpid()}",
                "amount": 20000,
                "customer_name": "API Client"
            }
        )
        self.assertEqual(resp_auth.status_code, 201)
        data = json.loads(resp_auth.data.decode())
        self.assertEqual(data["status"], "success")
        self.assertIn("checkout_url", data)
        inv_no = data["invoice_no"]
        total_amt = data["amount_total"]

        # 4. Test Public Checkout Page
        resp_checkout = self.client.get(f"/pay/{inv_no}")
        self.assertEqual(resp_checkout.status_code, 200)
        self.assertIn(inv_no.encode(), resp_checkout.data)

        # 5. Test Status API Poller
        resp_status = self.client.get(f"/api/v1/invoice/{inv_no}/status")
        self.assertEqual(resp_status.status_code, 200)
        st_data = json.loads(resp_status.data.decode())
        self.assertEqual(st_data["status"], "pending")

        # 6. Test Webhook Listener Triggering Completion
        webhook_secret = database.get_setting("webhook_secret", "")
        resp_webhook = self.client.post(
            "/api/v1/webhook/listener",
            headers={"X-Webhook-Secret": webhook_secret},
            json={
                "package": "com.gojek.merchant",
                "title": "Penerimaan GoPay",
                "body": f"Penerimaan GoPay: Rp {total_amt:,} berhasil diterima dari Donatur"
            }
        )
        self.assertEqual(resp_webhook.status_code, 200)
        wb_data = json.loads(resp_webhook.data.decode())
        self.assertTrue(wb_data["matched"])
        self.assertEqual(wb_data["invoice_no"], inv_no)

        # 7. Re-check Status API Poller -> should be completed!
        resp_status_after = self.client.get(f"/api/v1/invoice/{inv_no}/status")
        st_after = json.loads(resp_status_after.data.decode())
        self.assertEqual(st_after["status"], "completed")
        print("[PASS] test_04_api_create_and_checkout_endpoints")

if __name__ == "__main__":
    unittest.main()

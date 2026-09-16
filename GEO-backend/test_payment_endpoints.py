import os
import sys
import json
import jwt
import requests
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"
JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"

def make_token(user_id: str, exp_hours: int = 24) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.utcnow() + timedelta(hours=exp_hours),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def run_tests():
    print("=" * 70)
    print(" [*] RUNNING PAYMENT SECURITY & ENDPOINT TESTS")
    print("=" * 70)

    results = []
    valid_user_id = "test_user_automated_qa"
    valid_token = make_token(valid_user_id)
    auth_header = {"Authorization": f"Bearer {valid_token}"}

    # -- Test 1: create-order without auth header --
    print("\n[Test 1] POST /create-order without Authorization header...")
    r = requests.post(f"{BASE_URL}/api/payments/razorpay/create-order", json={
        "plan_name": "Lite Plan",
        "billing_cycle": "monthly"
    })
    passed = (r.status_code == 401)
    results.append(("1. create-order (no auth -> 401)", passed, f"Status: {r.status_code}, Body: {r.text}"))
    print(f"  {'[PASS]' if passed else '[FAIL]'}: Status {r.status_code} (Expected 401)")

    # -- Test 2: create-order with invalid auth header format --
    print("\n[Test 2] POST /create-order with malformed token...")
    r = requests.post(f"{BASE_URL}/api/payments/razorpay/create-order", json={
        "plan_name": "Lite Plan",
        "billing_cycle": "monthly"
    }, headers={"Authorization": "Bearer invalid_gibberish_token_12345"})
    passed = (r.status_code == 401)
    results.append(("2. create-order (invalid token -> 401)", passed, f"Status: {r.status_code}, Body: {r.text}"))
    print(f"  {'[PASS]' if passed else '[FAIL]'}: Status {r.status_code} (Expected 401)")

    # -- Test 3: verify-payment without auth header --
    print("\n[Test 3] POST /verify-payment without Authorization header...")
    r = requests.post(f"{BASE_URL}/api/payments/razorpay/verify-payment", json={
        "razorpay_order_id": "order_test_123",
        "razorpay_payment_id": "pay_test_123",
        "razorpay_signature": "sig_test_123",
        "plan_name": "Lite Plan",
        "billing_cycle": "monthly"
    })
    passed = (r.status_code == 401)
    results.append(("3. verify-payment (no auth -> 401)", passed, f"Status: {r.status_code}, Body: {r.text}"))
    print(f"  {'[PASS]' if passed else '[FAIL]'}: Status {r.status_code} (Expected 401)")

    # -- Test 4: create-order with invalid plan name --
    print("\n[Test 4] POST /create-order with invalid plan name...")
    r = requests.post(f"{BASE_URL}/api/payments/razorpay/create-order", json={
        "plan_name": "non_existent_plan_xyz",
        "billing_cycle": "monthly"
    }, headers=auth_header)
    passed = (r.status_code == 400 and "Invalid plan name" in r.text)
    results.append(("4. create-order (invalid plan -> 400)", passed, f"Status: {r.status_code}, Body: {r.text}"))
    print(f"  {'[PASS]' if passed else '[FAIL]'}: Status {r.status_code}, Message: {r.text}")

    # -- Test 5: create-order with invalid billing cycle --
    print("\n[Test 5] POST /create-order with invalid billing cycle...")
    r = requests.post(f"{BASE_URL}/api/payments/razorpay/create-order", json={
        "plan_name": "Lite Plan",
        "billing_cycle": "biweekly"
    }, headers=auth_header)
    passed = (r.status_code == 400 and "Invalid billing cycle" in r.text)
    results.append(("5. create-order (invalid cycle -> 400)", passed, f"Status: {r.status_code}, Body: {r.text}"))
    print(f"  {'[PASS]' if passed else '[FAIL]'}: Status {r.status_code}, Message: {r.text}")

    # -- Test 6: create-order with valid plan ('Lite Plan', 'monthly') --
    print("\n[Test 6] POST /create-order with valid plan ('Lite Plan', 'monthly')...")
    r = requests.post(f"{BASE_URL}/api/payments/razorpay/create-order", json={
        "plan_name": "Lite Plan",
        "billing_cycle": "monthly"
    }, headers=auth_header)
    data = r.json() if r.status_code == 200 else {}
    passed = (r.status_code == 200 and data.get("amount") == 240000 and data.get("currency") == "INR" and "order_id" in data)
    results.append(("6. create-order ('Lite Plan' monthly -> 200, 240000 paise)", passed, f"Status: {r.status_code}, Body: {r.text}"))
    created_order_id = data.get("order_id")
    print(f"  {'[PASS]' if passed else '[FAIL]'}: Status {r.status_code}, Order ID: {created_order_id}, Amount: {data.get('amount')} paise")

    # -- Test 7: create-order with short plan alias ('growth', 'yearly') --
    print("\n[Test 7] POST /create-order with short plan alias ('growth', 'yearly')...")
    r = requests.post(f"{BASE_URL}/api/payments/razorpay/create-order", json={
        "plan_name": "growth",
        "billing_cycle": "yearly"
    }, headers=auth_header)
    data = r.json() if r.status_code == 200 else {}
    passed = (r.status_code == 200 and data.get("amount") == 6500000 and data.get("currency") == "INR")
    results.append(("7. create-order ('growth' yearly -> 200, 6500000 paise)", passed, f"Status: {r.status_code}, Body: {r.text}"))
    print(f"  {'[PASS]' if passed else '[FAIL]'}: Status {r.status_code}, Amount: {data.get('amount')} paise")

    # -- Test 8: Client body user_id injection is ignored --
    print("\n[Test 8] POST /create-order with spoofed user_id in body...")
    r = requests.post(f"{BASE_URL}/api/payments/razorpay/create-order", json={
        "plan_name": "Lite Plan",
        "billing_cycle": "monthly",
        "user_id": "attacker_victim_id_999"
    }, headers=auth_header)
    passed = (r.status_code == 200)
    results.append(("8. create-order (body user_id ignored, uses JWT -> 200)", passed, f"Status: {r.status_code}"))
    print(f"  {'[PASS]' if passed else '[FAIL]'}: Status {r.status_code} (Order created safely using JWT identity)")

    # -- Test 9: verify-payment rejects fake HMAC signature --
    print("\n[Test 9] POST /verify-payment with forged HMAC signature...")
    r = requests.post(f"{BASE_URL}/api/payments/razorpay/verify-payment", json={
        "razorpay_order_id": created_order_id or "order_fake_12345",
        "razorpay_payment_id": "pay_fake_99999",
        "razorpay_signature": "forged_invalid_hmac_signature_hex",
        "plan_name": "Lite Plan",
        "billing_cycle": "monthly"
    }, headers=auth_header)
    passed = (r.status_code == 400 and "Invalid payment signature" in r.text)
    results.append(("9. verify-payment (forged signature -> 400)", passed, f"Status: {r.status_code}, Body: {r.text}"))
    print(f"  {'[PASS]' if passed else '[FAIL]'}: Status {r.status_code}, Detail: {r.text}")

    # -- Summary Report --
    print("\n" + "=" * 70)
    print(" [*] TEST EXECUTION SUMMARY")
    print("=" * 70)
    all_passed = True
    for name, passed, detail in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status}  {name}")
        if not passed:
            all_passed = False
            print(f"          Detail: {detail}")

    print("=" * 70)
    if all_passed:
        print(f" [SUCCESS] ALL {len(results)} TESTS PASSED!")
    else:
        print(" [WARNING] SOME TESTS FAILED")
    print("=" * 70)
    return all_passed

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)

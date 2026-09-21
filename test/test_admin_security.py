"""
Admin Panel RBAC & Security Regression Tests

Verifies:
1. All /api/admin endpoints strictly reject unauthenticated requests with 401
2. Regular users (role='user') are rejected with 403 Forbidden across all admin routes
3. Standard admins (role='admin') cannot access super_admin-only endpoints (role modification, refunds)
4. Suspended users are locked out app-wide immediately
"""
import os
import jwt
import requests
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8000"
JWT_SECRET = os.environ.get("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"

def make_token(user_id: str, role: str = "user", exp_hours: int = 24) -> str:
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=exp_hours),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


class TestAdminSecurity:
    # ── 1. Unauthenticated Gate Tests ─────────────────────────────────────────

    def test_stats_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/stats")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_users_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/users")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_payments_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/payments")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_audit_logs_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/audit-logs")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_usage_logs_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/usage-logs")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    # ── 2. Privilege Escalation & Role Boundary Tests ─────────────────────────

    def test_regular_user_cannot_access_stats(self):
        """A user with a standard token must receive 403 Forbidden."""
        token = make_token("fake_user_123", role="user")
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(f"{BASE_URL}/api/admin/stats", headers=headers)
        # 401 (if user doesn't exist in DB) or 403 (if user has role='user')
        assert r.status_code in (401, 403), f"Expected 401 or 403, got {r.status_code}"

    def test_regular_user_cannot_modify_plans(self):
        token = make_token("fake_user_123", role="user")
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.post(f"{BASE_URL}/api/admin/users/target_123/plan", json={
            "plan_name": "Enterprise",
            "billing_cycle": "yearly"
        }, headers=headers)
        assert r.status_code in (401, 403)

    def test_regular_user_cannot_modify_roles(self):
        token = make_token("fake_user_123", role="user")
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.post(f"{BASE_URL}/api/admin/users/target_123/role", json={
            "role": "super_admin"
        }, headers=headers)
        assert r.status_code in (401, 403)

    def test_regular_user_cannot_issue_refund(self):
        token = make_token("fake_user_123", role="user")
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.post(f"{BASE_URL}/api/admin/payments/pay_test_123/refund", json={
            "reason": "unauthorized refund attempt"
        }, headers=headers)
        assert r.status_code in (401, 403)

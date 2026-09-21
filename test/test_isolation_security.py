"""
Step 2 Security Regression Tests — Multi-Tenant Data Isolation & IDOR Protection

Tests verify:
1. /api/brands returns only the authenticated user's brands
2. /api/recent-analyses-by-brand/{brand} is scoped to the authenticated user
3. /api/analysis/status/{session_id} requires auth and enforces ownership
4. /api/analysis/citations/{session_id} enforces session ownership
5. /api/same-prompts-history/{session_id} enforces session ownership
"""
import pytest
import requests

BASE_URL = "http://localhost:8000"

# ---------------------------------------------------------------------------
# Fixtures — replace with real test credentials or generate from your test
# Supabase project.  The easiest approach is to have two pre-existing test
# users and one session owned by USER_A.
# ---------------------------------------------------------------------------
USER_A_TOKEN = "REPLACE_WITH_USER_A_JWT"
USER_B_TOKEN = "REPLACE_WITH_USER_B_JWT"
# A session_id that was created by USER_A
USER_A_SESSION_ID = "REPLACE_WITH_USER_A_SESSION_ID"

HEADERS_A = {"Authorization": f"Bearer {USER_A_TOKEN}"}
HEADERS_B = {"Authorization": f"Bearer {USER_B_TOKEN}"}
NO_AUTH = {}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def skip_if_placeholder(value: str, name: str):
    """Skip any test that still uses a placeholder value."""
    if value.startswith("REPLACE_WITH"):
        pytest.skip(f"{name} is still a placeholder — configure it to run this test")


# ---------------------------------------------------------------------------
# 1.  /api/brands — tenant-scoped
# ---------------------------------------------------------------------------
class TestBrandsEndpoint:
    def test_brands_requires_auth(self):
        """Without a token the endpoint must reject the request."""
        r = requests.get(f"{BASE_URL}/api/brands", headers=NO_AUTH)
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

    def test_brands_returns_only_own_brands(self):
        """User A and User B must get different (own) brand lists."""
        skip_if_placeholder(USER_A_TOKEN, "USER_A_TOKEN")
        skip_if_placeholder(USER_B_TOKEN, "USER_B_TOKEN")

        r_a = requests.get(f"{BASE_URL}/api/brands", headers=HEADERS_A)
        r_b = requests.get(f"{BASE_URL}/api/brands", headers=HEADERS_B)

        assert r_a.status_code == 200
        assert r_b.status_code == 200

        brands_a = set(r_a.json().get("brands", []))
        brands_b = set(r_b.json().get("brands", []))

        # The two brand lists must not be identical (they are different tenants)
        # NOTE: If both users genuinely have zero brands this test is a no-op.
        if brands_a and brands_b:
            assert brands_a != brands_b or len(brands_a) == 0 or len(brands_b) == 0, (
                "User A and User B should NOT share the same brand list — "
                "multi-tenant isolation failure"
            )


# ---------------------------------------------------------------------------
# 2.  /api/recent-analyses-by-brand/{brand_name} — tenant-scoped
# ---------------------------------------------------------------------------
class TestRecentAnalysesByBrand:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/recent-analyses-by-brand/TestBrand", headers=NO_AUTH)
        assert r.status_code == 401

    def test_user_b_cannot_see_user_a_sessions(self):
        """User B querying a brand that belongs to User A should get 0 sessions."""
        skip_if_placeholder(USER_A_TOKEN, "USER_A_TOKEN")
        skip_if_placeholder(USER_B_TOKEN, "USER_B_TOKEN")

        # First, get a brand name that User A owns
        brands_r = requests.get(f"{BASE_URL}/api/brands", headers=HEADERS_A)
        brands = brands_r.json().get("brands", [])
        if not brands:
            pytest.skip("User A has no brands — populate test data first")

        brand_name = brands[0]

        # User B queries that brand — should get no sessions
        r = requests.get(
            f"{BASE_URL}/api/recent-analyses-by-brand/{brand_name}",
            headers=HEADERS_B,
        )
        assert r.status_code == 200
        assert len(r.json().get("sessions", [])) == 0, (
            "User B should see 0 sessions for a brand owned by User A — "
            "multi-tenant isolation failure"
        )


# ---------------------------------------------------------------------------
# 3.  /api/analysis/status/{session_id} — IDOR protected
# ---------------------------------------------------------------------------
class TestStatusEndpointIDOR:
    def test_requires_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/analysis/status/some-session-id", headers=NO_AUTH
        )
        assert r.status_code == 401

    def test_owner_can_read_own_status(self):
        skip_if_placeholder(USER_A_TOKEN, "USER_A_TOKEN")
        skip_if_placeholder(USER_A_SESSION_ID, "USER_A_SESSION_ID")

        r = requests.get(
            f"{BASE_URL}/api/analysis/status/{USER_A_SESSION_ID}", headers=HEADERS_A
        )
        # 200 or 404 (no data) — both acceptable; 403 would be a bug
        assert r.status_code in (200, 404), f"Unexpected status {r.status_code}"

    def test_other_user_cannot_read_status(self):
        """User B must receive 403 when accessing User A's session status."""
        skip_if_placeholder(USER_B_TOKEN, "USER_B_TOKEN")
        skip_if_placeholder(USER_A_SESSION_ID, "USER_A_SESSION_ID")

        r = requests.get(
            f"{BASE_URL}/api/analysis/status/{USER_A_SESSION_ID}", headers=HEADERS_B
        )
        assert r.status_code == 403, (
            f"User B should get 403 for a session owned by User A, got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# 4.  /api/analysis/citations/{session_id} — IDOR protected
# ---------------------------------------------------------------------------
class TestCitationsEndpointIDOR:
    def test_requires_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/analysis/citations/some-session-id", headers=NO_AUTH
        )
        assert r.status_code == 401

    def test_other_user_cannot_read_citations(self):
        skip_if_placeholder(USER_B_TOKEN, "USER_B_TOKEN")
        skip_if_placeholder(USER_A_SESSION_ID, "USER_A_SESSION_ID")

        r = requests.get(
            f"{BASE_URL}/api/analysis/citations/{USER_A_SESSION_ID}", headers=HEADERS_B
        )
        assert r.status_code == 403, (
            f"User B should get 403 for citations of User A's session, got {r.status_code}"
        )


# ---------------------------------------------------------------------------
# 5.  /api/same-prompts-history/{session_id} — IDOR protected
# ---------------------------------------------------------------------------
class TestSamePromptsHistoryIDOR:
    def test_requires_auth(self):
        r = requests.get(
            f"{BASE_URL}/api/same-prompts-history/some-session-id", headers=NO_AUTH
        )
        assert r.status_code == 401

    def test_other_user_cannot_read_same_prompts_history(self):
        skip_if_placeholder(USER_B_TOKEN, "USER_B_TOKEN")
        skip_if_placeholder(USER_A_SESSION_ID, "USER_A_SESSION_ID")

        r = requests.get(
            f"{BASE_URL}/api/same-prompts-history/{USER_A_SESSION_ID}", headers=HEADERS_B
        )
        assert r.status_code == 403, (
            f"User B should get 403 for same-prompts-history of User A's session, got {r.status_code}"
        )

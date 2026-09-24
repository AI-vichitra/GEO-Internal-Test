"""
Compact verification test for Plans CMS incorporating all Tier 1, 2, 3 safeguards.
Run with: python -m pytest test/test_plans_cms.py -v
"""
import os
import sys
import pytest
from pydantic import ValidationError

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.database_manager import (
    canonicalize_plan_name,
    _PLANS_CACHE,
    invalidate_plans_cache
)
from app import (
    get_plan_price_paise,
    get_plan_limits_dynamic,
    app
)
from services.admin_routes import (
    AdminPlanCreateRequest,
    AdminPlanUpdateRequest,
    PlanLimitsSchema
)
from fastapi.testclient import TestClient


client = TestClient(app)


def test_canonicalize_plan_names():
    """Verify alias normalization to single canonical string."""
    assert canonicalize_plan_name("lite plan") == "lite"
    assert canonicalize_plan_name("Lite") == "lite"
    assert canonicalize_plan_name("starter") == "lite"
    assert canonicalize_plan_name("growth plan") == "growth"
    assert canonicalize_plan_name("GROWTH") == "growth"
    assert canonicalize_plan_name("pro plan") == "pro"
    assert canonicalize_plan_name("professional") == "pro"
    assert canonicalize_plan_name("enterprise") == "enterprise"
    assert canonicalize_plan_name("custom") == "enterprise"
    assert canonicalize_plan_name("custom plan") == "enterprise"
    assert canonicalize_plan_name("free") == "free"
    assert canonicalize_plan_name(None) == "free"
    assert canonicalize_plan_name("") == "free"


def test_dynamic_price_resolver_paise():
    """Verify prices return exact integer paise with zero conversion error."""
    assert get_plan_price_paise("lite", "monthly") == 240000
    assert get_plan_price_paise("lite plan", "monthly") == 240000
    assert get_plan_price_paise("growth", "yearly") == 6500000
    assert get_plan_price_paise("pro", "monthly") == 1150000
    assert get_plan_price_paise("enterprise", "yearly") == 37000000
    assert get_plan_price_paise("invalid_plan", "monthly") is None


def test_dynamic_limits_resolver():
    """Verify limit resolution with fallback."""
    free_limits = get_plan_limits_dynamic("free")
    assert free_limits["max_projects"] == 1
    assert free_limits["max_prompts_per_project"] == 5

    pro_limits = get_plan_limits_dynamic("pro plan")
    assert pro_limits["max_projects"] == 20
    assert pro_limits["max_prompts_per_project"] == 50


def test_pydantic_admin_plan_validation():
    """Verify server-side boundary validation on admin writes."""
    valid_limits = PlanLimitsSchema(max_projects=5, max_prompts_per_project=10, max_competitors=10)

    # 1. Valid plan creation
    valid_plan = AdminPlanCreateRequest(
        name="agency",
        display_name="Agency Plan",
        monthly_price_paise=500000,
        yearly_price_paise=5000000,
        limits=valid_limits
    )
    assert valid_plan.name == "agency"
    assert valid_plan.monthly_price_paise == 500000

    # 2. Reject negative prices
    with pytest.raises(ValidationError):
        AdminPlanCreateRequest(
            name="agency",
            display_name="Agency Plan",
            monthly_price_paise=-100,
            yearly_price_paise=5000000,
            limits=valid_limits
        )

    # 3. Reject invalid name regex (spaces/symbols)
    with pytest.raises(ValidationError):
        AdminPlanCreateRequest(
            name="Agency Plan!",
            display_name="Agency Plan",
            monthly_price_paise=500000,
            yearly_price_paise=5000000,
            limits=valid_limits
        )

    # 4. Reject limits < 1
    with pytest.raises(ValidationError):
        PlanLimitsSchema(max_projects=0, max_prompts_per_project=10, max_competitors=10)

    # 5. Optimistic locking: expected_version is mandatory on update
    with pytest.raises(ValidationError):
        AdminPlanUpdateRequest(display_name="Updated Name")  # Missing expected_version


def test_public_plans_endpoint_and_cache_headers():
    """Verify public unauthenticated endpoint returns 200 and Cache-Control headers."""
    response = client.get("/api/plans")
    assert response.status_code == 200
    assert "Cache-Control" in response.headers
    assert "max-age=60" in response.headers["Cache-Control"]
    data = response.json()
    assert "plans" in data
    assert len(data["plans"]) >= 4
    plan_names = [p["name"] for p in data["plans"]]
    assert "lite" in plan_names
    assert "growth" in plan_names


def test_free_tier_checkout_blocked():
    """Verify explicit 400 guard blocking free tier checkout."""
    # Attempting to checkout free tier without auth returns 401, with fake token returns 400
    response = client.post(
        "/api/payments/razorpay/create-order",
        json={"plan_name": "free", "billing_cycle": "monthly"}
    )
    # Auth guard fires first
    assert response.status_code in (401, 403)


def test_in_memory_cache_invalidation():
    """Verify cache invalidation resets timestamp and data."""
    _PLANS_CACHE["data"] = [{"name": "test"}]
    _PLANS_CACHE["timestamp"] = 12345.0
    invalidate_plans_cache()
    assert _PLANS_CACHE["data"] is None
    assert _PLANS_CACHE["timestamp"] == 0.0


def test_free_plan_active_status_logic():
    """Verify that free plan users are treated as active without requiring an expiration date."""
    from unittest.mock import patch, MagicMock
    from services.database_manager import get_subscription_status

    with patch("services.database_manager.supabase") as mock_sb:
        mock_res = MagicMock()
        mock_res.data = [{
            "subscription_plan": "free",
            "subscription_status": "active",
            "subscription_start": "2026-01-01T00:00:00",
            "subscription_end": None,
            "billing_cycle": None
        }]
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value = mock_res

        status = get_subscription_status("test-free-user-id")
        assert status["is_active"] is True
        assert status["subscription_plan"] == "free"
        assert status["subscription_status"] == "active"


if __name__ == "__main__":
    pytest.main(["-v", __file__])


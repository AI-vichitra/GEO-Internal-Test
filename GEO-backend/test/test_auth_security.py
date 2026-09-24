"""
Unit and integration tests for SEC-004 Auth & HttpOnly cookie security.
Run with: pytest test/test_auth_security.py -v
"""
import os
import sys
import pytest
from fastapi import Response, HTTPException
from fastapi.testclient import TestClient

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import (
    app,
    create_jwt_token,
    verify_jwt_token,
    set_auth_cookie,
    clear_auth_cookie,
    get_current_user
)
from services.admin_routes import require_admin
from unittest.mock import patch

client = TestClient(app)

SAMPLE_USER_ID = "00000000-0000-0000-0000-000000000001"
SAMPLE_ADMIN_ID = "00000000-0000-0000-0000-000000000002"


def test_set_auth_cookie_headers():
    """Verify set_auth_cookie properly configures HttpOnly, SameSite, and Path."""
    response = Response()
    token = create_jwt_token(SAMPLE_USER_ID)
    set_auth_cookie(response, token)
    
    # Check Set-Cookie header exists
    cookie_headers = response.raw_headers
    set_cookie_header = [v.decode() for k, v in cookie_headers if k.decode().lower() == "set-cookie"]
    assert len(set_cookie_header) > 0, "Set-Cookie header must be present"
    
    raw_cookie = set_cookie_header[0]
    assert "token=" in raw_cookie
    assert "HttpOnly" in raw_cookie or "httponly" in raw_cookie.lower()
    assert "samesite=lax" in raw_cookie.lower()
    assert "path=/" in raw_cookie.lower()
    assert "max-age=604800" in raw_cookie.lower()


def test_clear_auth_cookie():
    """Verify clear_auth_cookie deletes the auth cookie."""
    response = Response()
    clear_auth_cookie(response)
    cookie_headers = response.raw_headers
    set_cookie_header = [v.decode() for k, v in cookie_headers if k.decode().lower() == "set-cookie"]
    assert len(set_cookie_header) > 0
    raw_cookie = set_cookie_header[0]
    # delete_cookie sets max-age=0 or expires in past
    assert "max-age=0" in raw_cookie.lower() or "expires=" in raw_cookie.lower()


@patch("services.database_manager.get_user_by_id", return_value={"id": SAMPLE_USER_ID, "is_suspended": False})
def test_get_current_user_with_bearer_header(mock_db):
    """Verify get_current_user works with standard Authorization: Bearer <token>."""
    token = create_jwt_token(SAMPLE_USER_ID)
    user_id = get_current_user(authorization=f"Bearer {token}")
    assert user_id == SAMPLE_USER_ID


@patch("services.database_manager.get_user_by_id", return_value={"id": SAMPLE_USER_ID, "is_suspended": False})
def test_get_current_user_with_cookie_only(mock_db):
    """Verify get_current_user succeeds when Authorization header is absent but HttpOnly cookie is present."""
    token = create_jwt_token(SAMPLE_USER_ID)
    user_id = get_current_user(authorization=None, token=token)
    assert user_id == SAMPLE_USER_ID


@patch("services.database_manager.get_user_by_id", return_value={"id": SAMPLE_USER_ID, "is_suspended": False})
def test_get_current_user_bearer_null_fallback_to_cookie(mock_db):
    """Verify get_current_user falls back to cookie when header contains 'Bearer null' or 'Bearer undefined'."""
    token = create_jwt_token(SAMPLE_USER_ID)
    user_id = get_current_user(authorization="Bearer null", token=token)
    assert user_id == SAMPLE_USER_ID

    user_id2 = get_current_user(authorization="Bearer undefined", token=token)
    assert user_id2 == SAMPLE_USER_ID


def test_get_current_user_missing_credentials():
    """Verify get_current_user raises 401 when neither header nor cookie is provided."""
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization=None, token=None)
    assert exc_info.value.status_code == 401


def test_get_current_user_invalid_token():
    """Verify get_current_user raises 401 when given an invalid token."""
    with pytest.raises(HTTPException) as exc_info:
        get_current_user(authorization="Bearer invalid-token-xyz")
    assert exc_info.value.status_code == 401


def test_api_auth_logout_clears_cookie():
    """Verify POST /api/auth/logout returns a Set-Cookie header expiring the token."""
    res = client.post("/api/auth/logout")
    assert res.status_code == 200
    assert res.json().get("status") == "success"
    # Verify cookie clearance in response
    cookies = res.headers.get("set-cookie", "")
    assert "token=" in cookies
    assert "max-age=0" in cookies.lower() or "expires=" in cookies.lower()


@patch("services.database_manager.get_user_by_id", return_value={"id": SAMPLE_ADMIN_ID, "role": "admin", "is_suspended": False})
@patch("services.admin_routes.get_user_by_id", return_value={"id": SAMPLE_ADMIN_ID, "role": "admin", "is_suspended": False})
def test_admin_require_admin_cookie_support(mock_admin_db, mock_db):
    """Verify require_admin dependency works when admin token is provided via HttpOnly cookie."""
    token = create_jwt_token(SAMPLE_ADMIN_ID, role="admin")
    admin_user = require_admin(authorization=None, token=token)
    assert admin_user["user_id"] == SAMPLE_ADMIN_ID
    assert admin_user["role"] == "admin"

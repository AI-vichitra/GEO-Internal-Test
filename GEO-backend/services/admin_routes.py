import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel

from services.database_manager import (
    get_user_by_id,
    admin_list_users,
    admin_get_user_detail,
    admin_update_user,
    admin_list_payments,
    admin_update_payment,
    admin_get_stats,
    admin_list_audit_logs,
    admin_list_usage_logs,
    get_all_plans,
    get_plan_by_id,
    create_plan,
    update_plan,
    canonicalize_plan_name,
    supabase
)
from services.audit import log_admin_action
from services.payment_manager import payment_manager
from pydantic import Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["Admin Portal"])


# ─── RBAC DEPENDENCIES ────────────────────────────────────────────────────────

def get_client_ip(request: Request) -> str:
    """Extract client IP handling proxies/forwarded headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


from fastapi import Header, Cookie

def require_admin(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Cookie(None),
    token_cookie: Optional[str] = Cookie(None)
) -> Dict[str, Any]:
    """
    Validates that the current user has 'admin' or 'super_admin' role.
    Always checks real-time database state (never trusts JWT claim alone).
    """
    from app import get_current_user
    user_id = get_current_user(authorization=authorization, token=token, token_cookie=token_cookie)

    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    if user.get("is_suspended"):
        raise HTTPException(status_code=403, detail="Account is suspended")

    role = (user.get("role") or "user").lower()
    if role not in ("admin", "super_admin"):
        logger.warning(f"🚫 Access denied to /api/admin: User {user_id} has role '{role}'")
        raise HTTPException(status_code=403, detail="Admin privileges required")

    return {"user_id": user_id, "email": user.get("email"), "role": role}


async def require_super_admin(admin: Dict[str, Any] = Depends(require_admin)) -> Dict[str, Any]:
    """
    Restricts structural / destructive actions exclusively to 'super_admin'.
    """
    if admin.get("role") != "super_admin":
        logger.warning(f"🚫 Access denied to super_admin endpoint: User {admin.get('user_id')} is '{admin.get('role')}'")
        raise HTTPException(status_code=403, detail="Super Admin privileges required")
    return admin


# ─── REQUEST SCHEMAS ──────────────────────────────────────────────────────────

class PlanChangeRequest(BaseModel):
    plan_name: str
    billing_cycle: str = "monthly"
    duration_days: Optional[int] = None
    reason: Optional[str] = None


class CreditChangeRequest(BaseModel):
    amount: int
    reason: Optional[str] = None


class RoleChangeRequest(BaseModel):
    role: str  # 'user' | 'admin' | 'super_admin'
    reason: Optional[str] = None


class SuspendRequest(BaseModel):
    is_suspended: bool
    reason: Optional[str] = None


class RefundRequest(BaseModel):
    amount_paise: Optional[int] = None
    reason: Optional[str] = None


# ─── ENDPOINTS ────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats_endpoint(admin: Dict[str, Any] = Depends(require_admin)):
    """Retrieve overview metrics for Admin Dashboard."""
    return admin_get_stats()


@router.get("/users")
async def list_users_endpoint(
    search: Optional[str] = None,
    plan: Optional[str] = None,
    role: Optional[str] = None,
    is_suspended: Optional[bool] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """List users with search, filtering, and pagination."""
    return admin_list_users(search=search, plan=plan, role=role, is_suspended=is_suspended, page=page, limit=limit)


@router.get("/users/{user_id}")
async def get_user_detail_endpoint(
    user_id: str,
    admin: Dict[str, Any] = Depends(require_admin)
):
    """Get full profile details for a specific user."""
    user = admin_get_user_detail(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/users/{user_id}/plan")
async def update_user_plan_endpoint(
    user_id: str,
    request_body: PlanChangeRequest,
    req: Request,
    admin: Dict[str, Any] = Depends(require_admin)
):
    """Grant, upgrade, or revoke user subscription plan."""
    target_user = get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.now(timezone.utc)
    if request_body.duration_days:
        days = max(1, request_body.duration_days)
    else:
        days = 365 if request_body.billing_cycle.lower() == "yearly" else 30

    sub_end = (now + timedelta(days=days)).isoformat()
    status = "active" if request_body.plan_name.lower() != "free" else "inactive"

    fields = {
        "subscription_plan": request_body.plan_name,
        "subscription_status": status,
        "subscription_start": now.isoformat(),
        "subscription_end": sub_end,
        "billing_cycle": request_body.billing_cycle
    }

    success = admin_update_user(user_id, fields)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update user plan")

    log_admin_action(
        admin_user_id=admin["user_id"],
        action="grant_plan",
        target_type="user",
        target_id=user_id,
        details={
            "previous_plan": target_user.get("subscription_plan"),
            "new_plan": request_body.plan_name,
            "billing_cycle": request_body.billing_cycle,
            "subscription_end": sub_end,
            "reason": request_body.reason
        },
        ip_address=get_client_ip(req)
    )

    return {"success": True, "message": f"Plan updated to {request_body.plan_name}", "user": fields}


@router.post("/users/{user_id}/credits")
async def update_user_credits_endpoint(
    user_id: str,
    request_body: CreditChangeRequest,
    req: Request,
    admin: Dict[str, Any] = Depends(require_admin)
):
    """Add or adjust user analysis credits."""
    target_user = get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    current_remaining = int(target_user.get("credits_remaining") or 0)
    current_total = int(target_user.get("credits_total") or 0)

    new_remaining = max(0, current_remaining + request_body.amount)
    new_total = max(0, current_total + max(0, request_body.amount))

    success = admin_update_user(user_id, {
        "credits_remaining": new_remaining,
        "credits_total": new_total
    })
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update credits")

    log_admin_action(
        admin_user_id=admin["user_id"],
        action="grant_credits",
        target_type="user",
        target_id=user_id,
        details={
            "delta": request_body.amount,
            "previous_remaining": current_remaining,
            "new_remaining": new_remaining,
            "reason": request_body.reason
        },
        ip_address=get_client_ip(req)
    )

    return {"success": True, "credits_remaining": new_remaining, "credits_total": new_total}


@router.post("/users/{user_id}/suspend")
async def suspend_user_endpoint(
    user_id: str,
    request_body: SuspendRequest,
    req: Request,
    admin: Dict[str, Any] = Depends(require_admin)
):
    """Suspend or unsuspend a user (locks out of all endpoints)."""
    # Prevent self-suspension
    if admin["user_id"] == user_id:
        raise HTTPException(status_code=400, detail="Admins cannot suspend their own account")

    target_user = get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    success = admin_update_user(user_id, {"is_suspended": request_body.is_suspended})
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update suspension status")

    action_name = "suspend_user" if request_body.is_suspended else "unsuspend_user"
    log_admin_action(
        admin_user_id=admin["user_id"],
        action=action_name,
        target_type="user",
        target_id=user_id,
        details={"is_suspended": request_body.is_suspended, "reason": request_body.reason},
        ip_address=get_client_ip(req)
    )

    return {"success": True, "is_suspended": request_body.is_suspended}


@router.post("/users/{user_id}/role")
async def change_user_role_endpoint(
    user_id: str,
    request_body: RoleChangeRequest,
    req: Request,
    admin: Dict[str, Any] = Depends(require_super_admin)
):
    """Promote or demote user role (Super Admin only)."""
    allowed_roles = {"user", "admin", "super_admin"}
    target_role = request_body.role.lower().strip()
    if target_role not in allowed_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Allowed: {allowed_roles}")

    # Guard against self-demotion
    if admin["user_id"] == user_id and target_role != "super_admin":
        raise HTTPException(status_code=400, detail="Super Admins cannot demote their own account")

    target_user = get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    success = admin_update_user(user_id, {"role": target_role})
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update role")

    log_admin_action(
        admin_user_id=admin["user_id"],
        action="change_role",
        target_type="user",
        target_id=user_id,
        details={
            "previous_role": target_user.get("role", "user"),
            "new_role": target_role,
            "reason": request_body.reason
        },
        ip_address=get_client_ip(req)
    )

    return {"success": True, "role": target_role}


@router.get("/payments")
async def list_payments_endpoint(
    search: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """List payment transactions with search and pagination."""
    return admin_list_payments(search=search, status=status, page=page, limit=limit)


@router.post("/payments/{payment_id}/refund")
async def refund_payment_endpoint(
    payment_id: str,
    request_body: RefundRequest,
    req: Request,
    admin: Dict[str, Any] = Depends(require_super_admin)
):
    """Issue a refund via Razorpay (Super Admin only)."""
    # 1. Execute refund via Razorpay API
    refund_res = payment_manager.refund_payment(payment_id, request_body.amount_paise)
    if not refund_res:
        raise HTTPException(status_code=502, detail="Failed to issue refund via Razorpay gateway")

    refund_id = refund_res.get("id")

    # 2. Update payment transaction record
    admin_update_payment(payment_id, {
        "status": "refunded",
        "refund_id": refund_id
    })

    # 3. Log audit event
    log_admin_action(
        admin_user_id=admin["user_id"],
        action="refund_payment",
        target_type="payment_transaction",
        target_id=payment_id,
        details={
            "refund_id": refund_id,
            "amount_paise": request_body.amount_paise,
            "reason": request_body.reason
        },
        ip_address=get_client_ip(req)
    )

    return {"success": True, "refund_id": refund_id, "status": "refunded"}


@router.get("/audit-logs")
async def list_audit_logs_endpoint(
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """Retrieve immutable audit logs of admin activity."""
    return admin_list_audit_logs(action=action, target_type=target_type, page=page, limit=limit)


@router.get("/usage-logs")
async def list_usage_logs_endpoint(
    user_id: Optional[str] = None,
    activity_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: Dict[str, Any] = Depends(require_admin)
):
    """Retrieve user activity and LLM usage logs."""
    return admin_list_usage_logs(user_id=user_id, activity_type=activity_type, page=page, limit=limit)


# ─── PLANS CMS SCHEMAS & ENDPOINTS ──────────────────────────────────────────

class PlanLimitsSchema(BaseModel):
    max_projects: int = Field(..., ge=1)
    max_prompts_per_project: int = Field(..., ge=1)
    max_competitors: int = Field(..., ge=1)


class AdminPlanCreateRequest(BaseModel):
    name: str = Field(..., pattern=r"^[a-z0-9_-]+$", min_length=2, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    badge_text: Optional[str] = None
    monthly_price_paise: int = Field(..., ge=0)
    yearly_price_paise: int = Field(..., ge=0)
    currency: str = "INR"
    features: List[str] = Field(default_factory=list)
    limits: PlanLimitsSchema
    is_active: bool = True
    is_popular: bool = False
    cta_text: str = "Get Started"
    sort_order: int = 0
    grandfather_existing_subscribers: bool = False


class AdminPlanUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    badge_text: Optional[str] = None
    monthly_price_paise: Optional[int] = Field(None, ge=0)
    yearly_price_paise: Optional[int] = Field(None, ge=0)
    currency: Optional[str] = None
    features: Optional[List[str]] = None
    limits: Optional[PlanLimitsSchema] = None
    is_active: Optional[bool] = None
    is_popular: Optional[bool] = None
    cta_text: Optional[str] = None
    sort_order: Optional[int] = None
    grandfather_existing_subscribers: Optional[bool] = None
    expected_version: int = Field(..., description="Required for optimistic locking")
    change_reason: Optional[str] = None


@router.get("/plans")
async def list_admin_plans_endpoint(admin: Dict[str, Any] = Depends(require_admin)):
    """
    List all plans (active & inactive) with current subscriber counts.
    """
    plans = get_all_plans(active_only=False)
    
    # Calculate subscriber count per plan
    subscriber_counts: Dict[str, int] = {}
    try:
        users_res = supabase.table('users').select('subscription_plan').execute()
        for u in (users_res.data or []):
            plan_name = canonicalize_plan_name(u.get('subscription_plan'))
            subscriber_counts[plan_name] = subscriber_counts.get(plan_name, 0) + 1
    except Exception as count_err:
        logger.warning(f"Could not compute plan subscriber counts: {count_err}")

    for p in plans:
        canon = p.get('name', '')
        p['subscriber_count'] = subscriber_counts.get(canon, 0)

    return {"plans": plans}


@router.get("/plans/{plan_id}")
async def get_admin_plan_endpoint(plan_id: str, admin: Dict[str, Any] = Depends(require_admin)):
    """Retrieve details of a single plan."""
    plan = get_plan_by_id(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return {"plan": plan}


@router.post("/plans")
async def create_admin_plan_endpoint(
    request_body: AdminPlanCreateRequest,
    req: Request,
    admin: Dict[str, Any] = Depends(require_super_admin)
):
    """
    Create a new plan. Restricted exclusively to super_admin.
    """
    plan_dict = request_body.model_dump()
    if isinstance(plan_dict.get("limits"), BaseModel):
        plan_dict["limits"] = plan_dict["limits"].model_dump()

    try:
        new_plan = create_plan(plan_dict)
        log_admin_action(
            admin_user_id=admin.get("user_id"),
            action="create_plan",
            target_type="plan",
            target_id=str(new_plan.get("id")),
            details={"plan_name": new_plan.get("name"), "monthly_price_paise": new_plan.get("monthly_price_paise")},
            ip_address=get_client_ip(req)
        )
        return {"success": True, "plan": new_plan}
    except Exception as e:
        logger.error(f"Error creating plan: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to create plan: {str(e)}")


@router.put("/plans/{plan_id}")
async def update_admin_plan_endpoint(
    plan_id: str,
    request_body: AdminPlanUpdateRequest,
    req: Request,
    admin: Dict[str, Any] = Depends(require_super_admin)
):
    """
    Update plan with optimistic locking. Restricted exclusively to super_admin.
    """
    update_data = {k: v for k, v in request_body.model_dump().items() if v is not None}
    expected_version = update_data.pop("expected_version")
    if "limits" in update_data and isinstance(update_data["limits"], BaseModel):
        update_data["limits"] = update_data["limits"].model_dump()

    result = update_plan(
        plan_id=plan_id,
        fields=update_data,
        expected_version=expected_version,
        admin_user_id=admin.get("user_id")
    )

    log_admin_action(
        admin_user_id=admin.get("user_id"),
        action="update_plan",
        target_type="plan",
        target_id=plan_id,
        details={
            "plan_name": result["updated_plan"].get("name"),
            "old_version": expected_version,
            "new_version": result["updated_plan"].get("version"),
            "diff": result.get("diff", {})
        },
        ip_address=get_client_ip(req)
    )

    return {"success": True, "plan": result["updated_plan"], "diff": result.get("diff", {})}

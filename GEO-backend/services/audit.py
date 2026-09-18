import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Approximate costs per million tokens (USD)
# 1 token ≈ 4 characters
COST_RATES = {
    "claude": {
        "input_per_million": 3.00,    # Claude 3.5 Sonnet input
        "output_per_million": 15.00,  # Claude 3.5 Sonnet output
    },
    "mistral": {
        "input_per_million": 2.00,    # Mistral Large input
        "output_per_million": 6.00,   # Mistral Large output
    },
    "google_ai_overview": {
        "input_per_million": 0.50,
        "output_per_million": 1.50,
    },
    "default": {
        "input_per_million": 1.50,
        "output_per_million": 5.00,
    }
}

def estimate_llm_cost(llm_name: str, prompt_chars: int, response_chars: int) -> float:
    """
    Calculates estimated USD cost for an LLM call using character counts.
    Approximation: ~4 characters per token.
    """
    key = (llm_name or "").lower()
    matched_rate = COST_RATES.get("default")
    for rate_key in COST_RATES:
        if rate_key in key:
            matched_rate = COST_RATES[rate_key]
            break

    input_tokens = max(0, prompt_chars) / 4.0
    output_tokens = max(0, response_chars) / 4.0

    input_cost = (input_tokens / 1_000_000.0) * matched_rate["input_per_million"]
    output_cost = (output_tokens / 1_000_000.0) * matched_rate["output_per_million"]

    return round(input_cost + output_cost, 6)


def log_admin_action(
    admin_user_id: Optional[str],
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None
) -> bool:
    """
    Records an immutable audit log entry into admin_audit_logs via Supabase.
    """
    try:
        from services.database_manager import supabase
        
        entry = {
            "admin_user_id": admin_user_id,
            "action": action,
            "target_type": target_type,
            "target_id": str(target_id) if target_id else None,
            "details": details or {},
            "ip_address": ip_address,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        supabase.table("admin_audit_logs").insert(entry).execute()
        logger.info(f"🛡️ Admin Audit Log: [{action}] on {target_type}:{target_id} by {admin_user_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to record admin audit log: {e}", exc_info=True)
        return False


def log_usage(
    user_id: Optional[str],
    activity_type: str,
    session_id: Optional[str] = None,
    llm_name: Optional[str] = None,
    prompt_chars: int = 0,
    response_chars: int = 0,
    est_cost_usd: Optional[float] = None,
    meta: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Records platform usage into usage_logs via Supabase.
    """
    try:
        from services.database_manager import supabase

        if est_cost_usd is None and (prompt_chars > 0 or response_chars > 0):
            est_cost_usd = estimate_llm_cost(llm_name or "default", prompt_chars, response_chars)
        elif est_cost_usd is None:
            est_cost_usd = 0.0

        entry = {
            "user_id": user_id,
            "activity_type": activity_type,
            "session_id": session_id,
            "llm_name": llm_name,
            "prompt_chars": prompt_chars,
            "response_chars": response_chars,
            "est_cost_usd": est_cost_usd,
            "meta": meta or {},
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        supabase.table("usage_logs").insert(entry).execute()
        return True
    except Exception as e:
        # Non-critical: never break main user requests if usage logging fails
        logger.warning(f"Failed to record usage log: {e}")
        return False

"""
cron_security.py – HMAC-SHA256 webhook verification for the scheduler endpoint.

Usage:
    from services.cron_security import verify_cron_request
    if not verify_cron_request(dict(request.headers), await request.body()):
        raise HTTPException(status_code=401, detail="Unauthorized")

Required env var: CRON_SECRET (any long random string, e.g. 48+ chars)

Generating a signature (caller side):
    import hmac, hashlib, time
    ts    = str(int(time.time()))
    body  = b""          # empty POST body is fine
    sig   = hmac.new(CRON_SECRET.encode(), body + b":" + ts.encode(), hashlib.sha256).hexdigest()
    headers = {"X-Timestamp": ts, "X-Signature": sig}
"""
import hmac
import hashlib
import time
import os
import logging

logger = logging.getLogger(__name__)

# Maximum allowed clock drift in seconds (anti-replay window)
_MAX_DRIFT_SECONDS = 300  # 5 minutes


def verify_cron_request(headers: dict, raw_body: bytes) -> bool:
    """
    Validates an incoming cron/webhook request using HMAC-SHA256.

    Steps:
      1. Check X-Timestamp is present and within ±5 minutes of now.
      2. Recompute HMAC over (raw_body + b":" + timestamp_bytes).
      3. Compare with X-Signature using constant-time compare_digest.

    Returns True if valid, False otherwise.
    Logs the specific failure reason at WARNING level.
    """
    secret = os.environ.get("CRON_SECRET", "")
    if not secret:
        logger.warning("CRON_SECRET not configured – rejecting all cron requests")
        return False

    # Normalise header keys to lowercase
    h = {k.lower(): v for k, v in headers.items()}

    # 1. Check for Bearer token authorization (useful for cron-job.org / curl / webhooks)
    auth_header = h.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if hmac.compare_digest(token, secret):
            return True

    timestamp_str = h.get("x-timestamp", "")
    received_sig  = h.get("x-signature", "")

    if not timestamp_str or not received_sig:
        logger.warning("Cron request missing valid Authorization Bearer header or X-Timestamp/X-Signature headers")
        return False

    # 1. Replay check
    try:
        ts = int(timestamp_str)
    except ValueError:
        logger.warning("Cron X-Timestamp is not an integer")
        return False

    drift = abs(time.time() - ts)
    if drift > _MAX_DRIFT_SECONDS:
        logger.warning(f"Cron request timestamp drift too large: {drift:.0f}s (max {_MAX_DRIFT_SECONDS}s)")
        return False

    # 2. Recompute expected signature
    payload = raw_body + b":" + timestamp_str.encode()
    expected_sig = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()

    # 3. Constant-time comparison (prevents timing attacks)
    if hmac.compare_digest(expected_sig, received_sig):
        return True

    logger.warning("Cron X-Signature mismatch")
    return False


def make_cron_headers(body: bytes = b"") -> dict:
    """
    Convenience helper: generates the HMAC headers for a cron request.
    Use this in scripts that trigger the endpoint (e.g., curl helper, test code).
    """
    secret = os.environ.get("CRON_SECRET", "")
    if not secret:
        raise RuntimeError("CRON_SECRET not set")
    ts = str(int(time.time()))
    payload = body + b":" + ts.encode()
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return {"X-Timestamp": ts, "X-Signature": sig}

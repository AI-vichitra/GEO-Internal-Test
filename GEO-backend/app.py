from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Header, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPBasicCredentials
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging
import json
from dotenv import load_dotenv
import os
import sys
import asyncio

# ✅ FIX: Force ProactorEventLoop on Windows for Playwright compatibility
if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from supabase import create_client, Client
import bcrypt
import jwt
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
# Import your existing modules
from services.deep_research import conduct_deep_research
from services.prompt_generator import generate_prompts
from services.keyword_extractor import extract_keywords
from services.multi_llm_executor import execute_prompts_multi_llm_sync
from services.scoring_engine import calculate_scores, aggregate_results
from services.share_of_voice import calculate_share_of_voice
from services.url_keyword_extractor import extract_keywords_from_url
from services.payment_manager import payment_manager
from services.database_manager import (
    create_session_id, save_session, save_llm_response, 
    save_scoring_result, save_competitors, save_share_of_voice,
    get_session_results, get_all_sessions, init_database, create_prompt_id, get_recent_sessions,
    get_saved_prompts, save_prompts_to_db, save_brand_score_summary,
    signup_user, get_user_by_email, get_user_by_id, get_user_sessions,
    update_session_status, get_session_status, get_session_metadata, duplicate_session_cohorts,
    duplicate_session_competitors, replace_session_competitors, clear_session_metrics,
    activate_user_subscription, save_payment_transaction, get_subscription_status,
    get_all_plans, get_plan_by_name, canonicalize_plan_name
)
from services.database_manager import (
    get_all_unique_brands,
    get_recent_sessions_by_brand,
    get_saved_prompts_for_analysis,
    get_visibility_history_for_same_prompts,
    get_product_specific_visibility_history,
    create_project, get_user_projects, get_project_by_id, 
    update_project, delete_project, add_monitored_prompts, 
    get_monitored_prompts, add_monitored_competitors, 
    get_monitored_competitors, get_project_dashboard_metrics,
    claim_due_projects, release_project_lock, record_daily_metrics
)
from services.cron_security import verify_cron_request
# Setup
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# JWT Configuration (SEC-002)
_JWT_SECRET_RAW = os.environ.get("JWT_SECRET", "")
_INSECURE_DEFAULTS = {"your-secret-key-change-in-production", "secret", ""}
if not _JWT_SECRET_RAW or _JWT_SECRET_RAW in _INSECURE_DEFAULTS or len(_JWT_SECRET_RAW) < 32:
    raise RuntimeError(
        "[SEC-002] JWT_SECRET is missing, too short, or still set to an insecure default. "
        "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\" "
        "and set it in your .env file."
    )
JWT_SECRET = _JWT_SECRET_RAW
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24
# Log presence (not value) to help debug invalid tokens in different environments
logger.info(f"JWT secret present: True; length={len(JWT_SECRET)}")

# Admin bootstrap configuration
ADMIN_EMAILS = [e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()]
if ADMIN_EMAILS:
    logger.info(f"Admin bootstrap configured for {len(ADMIN_EMAILS)} email(s)")

# ============= CANONICAL PLAN PRICING (server-side source of truth) =============
# All amounts in paise (1 INR = 100 paise). Never trust client-supplied amounts.
PLAN_PRICES = {
    "lite plan":    {"monthly": 240000,  "yearly": 2400000},
    "growth plan":  {"monthly": 650000,  "yearly": 6500000},
    "pro plan":     {"monthly": 1150000, "yearly": 11500000},
    "enterprise":   {"monthly": 3700000, "yearly": 37000000},
    "lite":         {"monthly": 240000,  "yearly": 2400000},
    "growth":       {"monthly": 650000,  "yearly": 6500000},
    "pro":          {"monthly": 1150000, "yearly": 11500000},
}
 
# Initialize Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning(" SUPABASE_URL or SUPABASE_KEY not set - database operations may fail")
else:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    logger.info(" Supabase client initialized")
# Initialize database
init_database()

# ============= PRICING & PLAN LIMITS =============
# Enforces project and prompt limits based on the user's current subscription.
# Map for subscription_plan -> { limits }
PLAN_LIMITS = {
    "free": {"max_projects": 1, "max_prompts_per_project": 5, "max_competitors": 10},
    "lite plan": {"max_projects": 10, "max_prompts_per_project": 30, "max_competitors": 10},
    "growth plan": {"max_projects": 10, "max_prompts_per_project": 30, "max_competitors": 10},
    "custom plan": {"max_projects": 20, "max_prompts_per_project": 50, "max_competitors": 10},
    "pro plan": {"max_projects": 20, "max_prompts_per_project": 50, "max_competitors": 10},
    "enterprise": {"max_projects": 100, "max_prompts_per_project": 100, "max_competitors": 10},
    "lite": {"max_projects": 10, "max_prompts_per_project": 30, "max_competitors": 10},
    "growth": {"max_projects": 10, "max_prompts_per_project": 30, "max_competitors": 10},
    "custom": {"max_projects": 20, "max_prompts_per_project": 50, "max_competitors": 10},
    "pro": {"max_projects": 20, "max_prompts_per_project": 50, "max_competitors": 10}
}

# ============= DYNAMIC PLANS CMS RESOLVERS (with fallback) =============
USE_DB_PLANS = os.getenv("USE_DB_PLANS", "true").lower() == "true"


def get_plan_price_paise(plan_name: str, cycle: str) -> Optional[int]:
    """
    Returns the price in paise for a plan and billing cycle.
    Tries DB/cache first when USE_DB_PLANS is enabled, falling back to PLAN_PRICES.
    """
    cycle_key = cycle.lower()
    if USE_DB_PLANS:
        try:
            db_plan = get_plan_by_name(plan_name)
            if db_plan:
                if cycle_key == "yearly":
                    return int(db_plan.get("yearly_price_paise", 0))
                return int(db_plan.get("monthly_price_paise", 0))
        except Exception as e:
            logger.warning(f"Failed to fetch plan price from DB: {e}")

    # Fallback to hardcoded dict
    canon = canonicalize_plan_name(plan_name)
    if canon in PLAN_PRICES and cycle_key in PLAN_PRICES[canon]:
        return PLAN_PRICES[canon][cycle_key]
    return None


def get_plan_limits_dynamic(plan_name: str) -> Dict[str, Any]:
    """
    Returns limits for a plan.
    Tries DB/cache first when USE_DB_PLANS is enabled, falling back to PLAN_LIMITS.
    """
    canon = canonicalize_plan_name(plan_name)
    if USE_DB_PLANS:
        try:
            db_plan = get_plan_by_name(canon)
            if db_plan and db_plan.get("limits"):
                return db_plan["limits"]
        except Exception as e:
            logger.warning(f"Failed to fetch plan limits from DB: {e}")

    # Fallback to hardcoded dict
    return PLAN_LIMITS.get(canon, PLAN_LIMITS["free"])




# ============= PAID.AI & OPENTELEMETRY =============
PAID_API_KEY = os.environ.get("PAID_API_KEY")

try:
    from paid import Paid
    paid_client = Paid(token=PAID_API_KEY)
    logger.info("✅ Paid.ai client initialized successfully")
except Exception as e:
    logger.error(f"❌ Failed to initialize Paid.ai client: {str(e)}")
    paid_client = None

def send_signal(event_name: str, session_id: str, data: dict = None):
    """
    Sends business signals to Paid.ai. 
    session_id maps to external_customer_id to auto-create customers.
    """
    if not paid_client:
        return

    try:
        signal = {
            "event_name": event_name,
            "customer": {"external_customer_id": session_id},
            "attribution": {"external_product_id": "brand_visibility_analyzer"} 
        }
        
        if data:
            signal["data"] = data

        paid_client.signals.create_signals(signals=[signal])
        logger.info(f"✅ Sent signal to Paid: {event_name}")
    except Exception as e:
        logger.error(f"❌ Error sending signal: {str(e)}")

# Initialize opentelemetry for Paid.ai Traces
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    
    # Import specific instrumentors for your LLMs
    from openinference.instrumentation.anthropic import AnthropicInstrumentor
    from openinference.instrumentation.openai import OpenAIInstrumentor
    from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor

    if PAID_API_KEY:
        # MUST use the dedicated collector URL and the x-api-key header
        endpoint = "https://collector.agentpaid.io:4318/v1/traces"
        headers = {
            "x-api-key": PAID_API_KEY,
            "Authorization": f"Bearer {PAID_API_KEY}" # Sent as a fallback
        }

        provider = TracerProvider()
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, headers=headers))
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

        # Boot the auto-instrumentation
        AnthropicInstrumentor().instrument()
        OpenAIInstrumentor().instrument()
        GoogleGenAIInstrumentor().instrument()
        
        logger.info("✅ Paid.ai OpenTelemetry tracking initialized for LLMs (Claude, ChatGPT, Gemini)")
    else:
        logger.warning("❌ PAID_API_KEY not found, skipping OpenTelemetry configuration.")
except Exception as otel_err:
    logger.error(f"❌ Failed to initialize OpenTelemetry: {otel_err}")

# FastAPI app
app = FastAPI(
    title="Brand Visibility Analyzer API",
    description="Backend API for brand visibility analysis",
    version="1.0.0"
)
# ============= CORS MIDDLEWARE (SEC-003) =============
origins = [
    # Production
    "http://geocc.duckdns.org",
    "https://geocc.duckdns.org",
    "http://geocc.duckdns.org:3000",
    "http://geocc.duckdns.org:8000",
    # Staging
    "http://geotest2026.duckdns.org",
    "https://geotest2026.duckdns.org",
    "http://geotest2026.duckdns.org:3000",
    "http://geotest2026.duckdns.org:8000",
    # Local Development
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    # VM Direct IPs (Staging & Production VM fallbacks)
    "http://34.44.17.192",
    "http://34.44.17.192:3000",
    "http://34.44.17.192:8000",
    "http://34.42.234.69",
    "http://34.42.234.69:3000",
    "http://34.42.234.69:8000",
]

# Allow overriding or adding origins via FRONTEND_URL environment variable
frontend_env = os.environ.get("FRONTEND_URL")
if frontend_env:
    for url in [u.strip() for u in frontend_env.split(",") if u.strip()]:
        if url not in origins:
            origins.append(url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def on_startup():
    """Start optional in-process scheduler loop (for single-server setups)."""
    if os.environ.get("ENABLE_SCHEDULER", "false").lower() == "true":
        from services.scheduler import start_scheduler_loop
        interval = int(os.environ.get("SCHEDULER_INTERVAL_SECONDS", "3600"))
        start_scheduler_loop(interval)
        logger.info(f"✅ In-process scheduler started (interval={interval}s)")

# ============= REQUEST MODELS =============

class SignUpRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class GoogleAuthRequest(BaseModel):
    token: str

class RazorpayOrderRequest(BaseModel):
    plan_name: str
    billing_cycle: str
    user_id: Optional[str] = None  # Ignored server-side; identity comes from JWT

class RazorpayVerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    user_id: Optional[str] = None  # Ignored server-side; identity comes from JWT
    plan_name: str
    billing_cycle: str

class CustomExecutionRequest(BaseModel):
    prompts: List[str]
    llms: List[str]

class CompetitorUpdateRequest(BaseModel):
    competitors: List[str]

class AnalysisRequest(BaseModel):
    brand_name: str
    product_name: Optional[str] = None
    industry: Optional[str] = None
    website_url: Optional[str] = None
    selected_llms: List[str] = []
    regenerate_prompts: bool = True
    custom_keywords: Optional[List[str]] = None
    custom_competitors: Optional[List[str]] = None
    project_id: Optional[str] = None
    brand_aliases: Optional[List[str]] = None

class ResearchRequest(BaseModel):
    brand_name: str
    website_url: Optional[str] = None
    industry: Optional[str] = None
    custom_competitors: Optional[List[str]] = None

class ProjectCreateRequest(BaseModel):
    name: str
    website_url: Optional[str] = None
    industry: Optional[str] = None
    update_frequency: str = "24h"
    initial_prompts: Optional[List[str]] = []
    initial_competitors: Optional[List[str]] = []

class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    website_url: Optional[str] = None
    industry: Optional[str] = None
    update_frequency: Optional[str] = None
    is_active: Optional[bool] = None

class SeoAnalysisRequest(BaseModel):
    url: str
    skills: List[str]


# ============= API ENDPOINTS =============

# ============= AUTHENTICATION HELPERS =============
def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash"""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False

def create_jwt_token(user_id: str, role: str = "user") -> str:
    """Create a JWT token for a user with embedded role"""
    payload = {
        'user_id': user_id,
        'role': role,
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.utcnow()
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    # PyJWT may return bytes in some versions; ensure string is returned
    if isinstance(token, bytes):
        token = token.decode('utf-8')
    return token


def verify_jwt_token(token: str) -> Optional[str]:
    """Verify a JWT token and return the user_id"""
    if not token:
        return None

    # Sanitize token (strip surrounding quotes/whitespace which can appear from bad storage)
    token = token.strip().strip('"').strip("'")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get('user_id')
    except jwt.ExpiredSignatureError as e:
        logger.info(f"JWT expired: {str(e)}")
        return None
    except jwt.InvalidTokenError as e:
        logger.info(f"Invalid JWT: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error decoding JWT: {str(e)}")
        return None

def set_auth_cookie(response: Response, token: str):
    """Sets secure HttpOnly cookie for session management (SEC-004)."""
    is_prod = os.environ.get("ENVIRONMENT", "development").lower() == "production"
    response.set_cookie(
        key="token",
        value=token,
        httponly=True,
        secure=is_prod,
        samesite="lax",
        max_age=7 * 86400,
        path="/"
    )

def clear_auth_cookie(response: Response):
    """Clears HttpOnly auth cookie on logout (SEC-004)."""
    response.delete_cookie(key="token", path="/")

from fastapi import Cookie

def get_current_user(
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Cookie(None),
    token_cookie: Optional[str] = Cookie(None)
) -> str:
    """Dependency to get current authenticated user. Accepts Authorization header or 'token'/'token_cookie' HttpOnly cookie."""
    cookie_token = token or token_cookie

    # If authorization header is absent, empty, or dummy "Bearer null"/"Bearer undefined", fall back to cookie
    if not authorization or authorization.strip() in ("Bearer", "Bearer null", "Bearer undefined"):
        if cookie_token:
            authorization = f"Bearer {cookie_token}"

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")

    try:
        parts = authorization.split()
        if len(parts) != 2:
            raise HTTPException(status_code=401, detail="Invalid authorization header")

        scheme, raw_token = parts
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")

        user_id = verify_jwt_token(raw_token)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        # Real-time DB suspension check (defense in depth)
        from services.database_manager import get_user_by_id
        user_row = get_user_by_id(str(user_id))
        if user_row and user_row.get("is_suspended"):
            logger.warning(f"🚫 Suspended user {user_id} attempted access")
            raise HTTPException(status_code=403, detail="Account is suspended. Please contact support.")

        return str(user_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth error: {str(e)}")
        raise HTTPException(status_code=401, detail="Authentication failed")

def verify_session_owner(session_id: str, user_id: str) -> dict:
    """
    Verifies that the session exists and belongs to the authenticated user.
    Prevents IDOR (Insecure Direct Object Reference).
    Returns the session metadata dictionary on success.
    """
    session_metadata = get_session_metadata(session_id)
    if not session_metadata:
        raise HTTPException(status_code=404, detail="Session not found")

    stored_user_id = session_metadata.get('user_id')
    if stored_user_id and str(stored_user_id) != str(user_id):
        logger.warning(f"🚫 Access denied: User {user_id} tried to access session {session_id} owned by {stored_user_id}")
        raise HTTPException(status_code=403, detail="Access denied: you do not have permission to access this session")

    return session_metadata

# ============= AUTHENTICATION ENDPOINTS =============
@app.post("/api/auth/signup")
async def signup(request: SignUpRequest, response: Response):
    """Register a new user and set HttpOnly session cookie (SEC-004)"""
    try:
        if not request.email or not request.password:
            raise HTTPException(status_code=400, detail="Email and password are required")
        
        if len(request.password) < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
        
        # Check if user already exists
        existing_user = get_user_by_email(request.email)
        if existing_user:
            raise HTTPException(status_code=400, detail="User with this email already exists")
        
        # Hash password and create user
        password_hash = hash_password(request.password)
        user_id = signup_user(request.email, password_hash)
        
        if not user_id:
            raise HTTPException(status_code=500, detail="Failed to create user")
        
        # Create JWT token and set HttpOnly session cookie
        token = create_jwt_token(user_id)
        set_auth_cookie(response, token)
        
        # Fetch subscription status and plan limits to return alongside token
        sub_status = get_subscription_status(user_id)
        plan_name = sub_status.get("subscription_plan") or "free"
        plan_limits = get_plan_limits_dynamic(plan_name)

        return {
            "status": "success",
            "user_id": user_id,
            "email": request.email,
            "role": "user",
            "token": token,
            "subscription": sub_status,
            "plan_limits": plan_limits,
            "message": "User registered successfully"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Signup failed: {str(e)}")

@app.post("/api/auth/login")
async def login(request: LoginRequest, response: Response):
    """Login user, return JWT token, and set HttpOnly session cookie (SEC-004)"""
    try:
        if not request.email or not request.password:
            raise HTTPException(status_code=400, detail="Email and password are required")
        
        # Get user from database
        user = get_user_by_email(request.email)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        # Verify password
        if not verify_password(request.password, user['password_hash']):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        # Check real-time suspension on login
        if user.get("is_suspended"):
            raise HTTPException(status_code=403, detail="Account is suspended. Please contact support.")

        # Check admin bootstrap
        user_role = (user.get("role") or "user").lower()
        if request.email.lower() in ADMIN_EMAILS and user_role != "super_admin":
            from services.database_manager import admin_update_user
            admin_update_user(user["id"], {"role": "super_admin"})
            user_role = "super_admin"
            logger.info(f"👑 Bootstrapped super_admin role for {request.email}")

        # Create JWT token with role and set HttpOnly session cookie
        token = create_jwt_token(user['id'], role=user_role)
        set_auth_cookie(response, token)

        # Fetch subscription status and plan limits to return alongside token
        sub_status = get_subscription_status(user['id'])
        plan_name = sub_status.get("subscription_plan") or "free"
        plan_limits = get_plan_limits_dynamic(plan_name)

        return {
            "status": "success",
            "user_id": user['id'],
            "email": user['email'],
            "role": user_role,
            "token": token,
            "subscription": sub_status,
            "plan_limits": plan_limits,
            "message": "Login successful"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")

@app.post("/api/auth/google")
async def google_auth(request: GoogleAuthRequest, response: Response):
    """Verify Google token, login/signup user, and set HttpOnly session cookie (SEC-004)"""
    try:
        # Verify the Google token
        client_id = os.environ.get("GOOGLE_CLIENT_ID")
        if not client_id:
            raise HTTPException(status_code=500, detail="Google Client ID not configured")
            
        try:
            idinfo = id_token.verify_oauth2_token(
                request.token, 
                google_requests.Request(), 
                client_id
            )
            
            # ID token is valid. Get the user's Google ID and email
            email = idinfo['email']
            google_id = idinfo['sub']
            
        except ValueError as e:
            # Invalid token
            logger.error(f"Invalid Google token: {str(e)}")
            raise HTTPException(status_code=401, detail="Invalid Google token")
        
        # Check if user already exists
        user = get_user_by_email(email)
        
        if not user:
            # Auto-signup for Google users
            # Use a placeholder hash since we don't have a password for Google users
            # The 'SOCIAL_AUTH' prefix helps identify these users
            placeholder_hash = "SOCIAL_AUTH_GOOGLE_" + google_id
            user_id = signup_user(email, placeholder_hash)
            
            if not user_id:
                raise HTTPException(status_code=500, detail="Failed to create user during Google sign-in")
                
            user = {"id": user_id, "email": email, "role": "user"}
        
        user_role = (user.get("role") or "user").lower()

        # Create JWT token and set HttpOnly session cookie
        token = create_jwt_token(user['id'], role=user_role)
        set_auth_cookie(response, token)

        # Fetch subscription status and plan limits to return alongside token
        sub_status = get_subscription_status(user['id'])
        plan_name = sub_status.get("subscription_plan") or "free"
        plan_limits = get_plan_limits_dynamic(plan_name)

        return {
            "status": "success",
            "user_id": user['id'],
            "email": user['email'],
            "role": user_role,
            "token": token,
            "subscription": sub_status,
            "plan_limits": plan_limits,
            "message": "Google Login successful"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Google auth error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Google authentication failed: {str(e)}")


@app.post("/api/auth/logout")
async def logout(response: Response):
    """Clear HttpOnly session cookie on logout (SEC-004)"""
    clear_auth_cookie(response)
    return {"status": "success", "message": "Logged out successfully"}


@app.get("/api/auth/me")
async def get_current_user_info(response: Response, user_id: str = Depends(get_current_user)):
    """Get current user information and return active token for in-memory client state (SEC-004)"""
    try:
        user = get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Issue fresh in-memory token and refresh HttpOnly cookie
        token = create_jwt_token(user_id, role=user.get("role", "user"))
        set_auth_cookie(response, token)

        return {
            "status": "success",
            "user": user,
            "token": token
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user info: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve user info")
    except Exception as e:
        logger.error(f"Error getting user info: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve user info")

from fastapi import Request
from fastapi.responses import JSONResponse

@app.get("/api/users/me")
async def get_current_user_info_alias(request: Request):
    """Alias for /api/auth/me — swallows calls from browser extensions silently."""
    # We bypass Depends(get_current_user) carefully so we don't spam the logs with 
    # "Checking auth..." and "Authorization missing" every time an extension hits this.
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        # Return 200 OK silently to prevent users from thinking the 401 log is a critical error
        return JSONResponse(status_code=200, content={"status": "not_logged_in", "user": None})
        
    try:
        token = auth_header.split()[1]
        user_id = verify_jwt_token(token)
        if not user_id:
            return JSONResponse(status_code=200, content={"status": "not_logged_in", "user": None})
            
        user = get_user_by_id(user_id)
        if not user:
            return JSONResponse(status_code=200, content={"status": "not_logged_in", "user": None})
            
        return {"status": "success", "user": user}
    except Exception:
        return JSONResponse(status_code=200, content={"status": "not_logged_in", "user": None})

# ============= PUBLIC PRICING PLANS ENDPOINT =============

@app.get("/api/plans")
async def get_public_plans(response: Response):
    """
    Public pricing plans endpoint (unauthenticated).
    Returns all active plans sorted by sort_order.
    Cached for 60 seconds at browser and edge CDN layer.
    """
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=30"
    if USE_DB_PLANS:
        try:
            db_plans = get_all_plans(active_only=True)
            if db_plans:
                return {"plans": db_plans}
        except Exception as e:
            logger.warning(f"Error fetching public plans from DB: {e}")

    # Fallback to hardcoded plan definitions if DB is unavailable
    fallback_plans = [
        {
            "name": "free", "display_name": "Free", "description": "Get started with essential AI visibility metrics.",
            "badge_text": None, "monthly_price_paise": 0, "yearly_price_paise": 0, "currency": "INR",
            "features": ["1 Brand Project", "Up to 5 Prompts/queries per project", "Up to 10 Competitors tracked", "AI Engine Rankings (Claude, Mistral, Google AIO)", "Basic sentiment & engine presence", "Community support"],
            "limits": {"max_projects": 1, "max_prompts_per_project": 5, "max_competitors": 10}, "is_active": True, "is_popular": False, "cta_text": "Start Free", "sort_order": 0
        },
        {
            "name": "lite", "display_name": "Lite", "description": "Essential AI search monitoring for emerging brands.",
            "badge_text": None, "monthly_price_paise": 240000, "yearly_price_paise": 2400000, "currency": "INR",
            "features": ["10 Brand Projects", "Up to 30 Prompts/queries per project", "Up to 10 Competitors tracked", "AI Engine Rankings (Claude, Mistral, Google AIO)", "AI Recommendations Engine", "Standard email support"],
            "limits": {"max_projects": 10, "max_prompts_per_project": 30, "max_competitors": 10}, "is_active": True, "is_popular": False, "cta_text": "Upgrade to Lite", "sort_order": 1
        },
        {
            "name": "growth", "display_name": "Growth", "description": "Complete GEO toolset for growing brands & marketing teams.",
            "badge_text": "MOST POPULAR", "monthly_price_paise": 650000, "yearly_price_paise": 6500000, "currency": "INR",
            "features": ["10 Brand Projects", "Up to 30 Prompts/queries per project", "Up to 10 Competitors tracked", "All AI Engine Rankings + Deeper analysis", "AI Recommendations Engine", "Full Competitor Analysis & overlap matrix", "Priority email & chat support"],
            "limits": {"max_projects": 10, "max_prompts_per_project": 30, "max_competitors": 10}, "is_active": True, "is_popular": True, "cta_text": "Upgrade to Growth", "sort_order": 2
        },
        {
            "name": "pro", "display_name": "Pro", "description": "Maximum scale, deep analytics and tailored support for agencies.",
            "badge_text": None, "monthly_price_paise": 1150000, "yearly_price_paise": 11500000, "currency": "INR",
            "features": ["20 Brand Projects", "Up to 50 Prompts/queries per project", "Up to 10 Competitors tracked", "All AI Engines with highest sampling frequency", "Advanced Competitor Benchmark & gap analysis", "Automated scheduled tracking runs", "Dedicated account manager"],
            "limits": {"max_projects": 20, "max_prompts_per_project": 50, "max_competitors": 10}, "is_active": True, "is_popular": False, "cta_text": "Upgrade to Pro", "sort_order": 3
        },
        {
            "name": "enterprise", "display_name": "Enterprise", "description": "Custom deployment, dedicated infrastructure, and unlimited scale.",
            "badge_text": None, "monthly_price_paise": 3700000, "yearly_price_paise": 37000000, "currency": "INR",
            "features": ["100 Brand Projects", "Up to 100 Prompts/queries per project", "Up to 10 Competitors tracked", "Custom AI models integration", "SLA guarantee (99.9% uptime)", "Custom reporting & webhook alerts", "24/7 Priority Support"],
            "limits": {"max_projects": 100, "max_prompts_per_project": 100, "max_competitors": 10}, "is_active": True, "is_popular": False, "cta_text": "Contact Sales", "sort_order": 4
        }
    ]
    return {"plans": fallback_plans}


# ============= PAYMENT ENDPOINTS (RAZORPAY) =============

@app.post("/api/payments/razorpay/create-order")
async def create_razorpay_order(
    request: RazorpayOrderRequest,
    current_user_id: str = Depends(get_current_user)
):
    """Create a new Razorpay order for a specific plan (JWT-protected)"""
    try:
        plan_key = canonicalize_plan_name(request.plan_name)
        if plan_key == "free":
            raise HTTPException(status_code=400, detail="Free plan cannot be purchased via payment checkout")

        cycle = request.billing_cycle.lower()
        if cycle not in ("monthly", "yearly"):
            raise HTTPException(status_code=400, detail="Invalid billing cycle")

        amount = get_plan_price_paise(plan_key, cycle)
        if amount is None or amount <= 0:
            raise HTTPException(status_code=400, detail="Invalid plan name or price is zero")

        # Shorten user_id to fit Razorpay's 40-char receipt limit
        short_id = current_user_id[:8]
        receipt_id = f"rcpt_{short_id}_{int(datetime.now().timestamp())}"

        order = payment_manager.create_order(
            amount=amount,
            currency="INR",
            receipt=receipt_id
        )

        if not order:
            raise HTTPException(status_code=500, detail="Failed to create Razorpay order")

        logger.info(f"✅ Razorpay order created for user={current_user_id} plan={plan_key} cycle={cycle} amount={amount}")

        return {
            "status": "success",
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key_id": os.environ.get("RAZORPAY_KEY_ID")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_razorpay_order: {str(e)}")
        raise HTTPException(status_code=500, detail="An internal error occurred")

@app.post("/api/payments/razorpay/verify-payment")
async def verify_razorpay_payment(
    request: RazorpayVerifyRequest,
    current_user_id: str = Depends(get_current_user)
):
    """
    Verify Razorpay payment signature and activate user subscription (JWT-protected).
    Security flow:
      1. HMAC-SHA256 signature verification (prevents forged callbacks)
      2. Server-side order amount verification (prevents plan escalation attacks)
      3. User existence guard (identity from JWT, not client body)
      4. Idempotency guard via payment_transactions UNIQUE constraint
      5. Immutable audit log written BEFORE subscription activation with actual amount snapshot
      6. Subscription activated exclusively for the JWT-authenticated user
    """
    try:
        # ── 1. Cryptographic Signature Verification ───────────────────────────
        is_valid = payment_manager.verify_signature(
            order_id=request.razorpay_order_id,
            payment_id=request.razorpay_payment_id,
            signature=request.razorpay_signature
        )
        if not is_valid:
            logger.warning(f"❌ Invalid Razorpay signature for order {request.razorpay_order_id}")
            raise HTTPException(status_code=400, detail="Invalid payment signature")

        # ── 2. Server-Side Plan Price Verification (prevents plan escalation) ──
        plan_key = canonicalize_plan_name(request.plan_name)
        cycle = request.billing_cycle.lower()

        if cycle not in ("monthly", "yearly"):
            raise HTTPException(status_code=400, detail="Invalid billing cycle")

        expected_amount = get_plan_price_paise(plan_key, cycle)
        if expected_amount is None:
            raise HTTPException(status_code=400, detail="Invalid plan name")

        razorpay_order = payment_manager.fetch_order(request.razorpay_order_id)
        if not razorpay_order:
            raise HTTPException(status_code=502, detail="Could not verify order with payment provider")

        actual_amount = int(razorpay_order.get("amount", 0))
        actual_currency = razorpay_order.get("currency", "")

        if actual_amount != expected_amount or actual_currency != "INR":
            logger.warning(
                f"🚨 Plan escalation attempt blocked! "
                f"user={current_user_id} claimed plan={plan_key} (expected {expected_amount} paise) "
                f"but order amount={actual_amount} currency={actual_currency}"
            )
            raise HTTPException(status_code=400, detail="Order amount does not match plan price")

        # ── 3. User Guard (JWT identity — do NOT use client-supplied user_id) ──
        user = get_user_by_id(current_user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user_email = user.get('email', '')

        # ── 4 & 5. Idempotency + Audit Log ────────────────────────────────────
        from datetime import timezone
        now = datetime.now(timezone.utc)
        days = 365 if cycle == "yearly" else 30
        subscription_end_iso = (now + timedelta(days=days)).isoformat()

        try:
            save_payment_transaction(
                user_id=current_user_id,
                user_email=user_email,
                razorpay_order_id=request.razorpay_order_id,
                razorpay_payment_id=request.razorpay_payment_id,
                razorpay_signature=request.razorpay_signature,
                plan_name=plan_key,
                billing_cycle=request.billing_cycle,
                subscription_end=subscription_end_iso,
                amount_paise=actual_amount,
                currency=actual_currency
            )
        except Exception as audit_err:
            err_str = str(audit_err).lower()
            if 'unique' in err_str or 'duplicate' in err_str:
                logger.warning(f"⚠️ Duplicate payment attempt blocked: {request.razorpay_payment_id}")
                raise HTTPException(status_code=409, detail="This payment has already been processed")
            logger.warning(f"⚠️ Could not save payment_transaction (table may be missing): {audit_err}")

        # ── 6. Activate Subscription for the authenticated user ───────────────
        activated = activate_user_subscription(
            user_id=current_user_id,
            plan_name=request.plan_name,
            billing_cycle=request.billing_cycle,
            razorpay_payment_id=request.razorpay_payment_id
        )
        if not activated:
            raise HTTPException(status_code=500, detail="Payment verified but subscription activation failed")

        logger.info(f"✅ Subscription activated for user={current_user_id} plan={plan_key} cycle={cycle}")

        return {
            "status": "success",
            "message": "Payment verified and subscription activated successfully",
            "subscription_end": subscription_end_iso
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in verify_razorpay_payment: {str(e)}")
        raise HTTPException(status_code=500, detail="An internal error occurred")


@app.get("/api/payments/subscription-status")
async def check_subscription_status(user_id: str = Depends(get_current_user)):
    """
    JWT-protected endpoint. Returns the current subscription status for the
    logged-in user, plus the DB-driven plan limits so the frontend never
    needs a hardcoded lookup table.
    """
    try:
        status = get_subscription_status(user_id)
        plan_name = status.get("subscription_plan") or "free"
        plan_limits = get_plan_limits_dynamic(plan_name)
        return {"status": "success", "subscription": status, "plan_limits": plan_limits}
    except Exception as e:
        logger.error(f"Error fetching subscription status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch subscription status")


@app.get("/health")
def health_check():
    """Check if API is running"""
    return {
        "status": "healthy",
        "message": "API is running!",
        "database": "Supabase"
    }

# In app.py - Update the /api/analysis/run endpoint

@app.post("/api/analysis/research")
async def conduct_research_endpoint(request: ResearchRequest, user_id: str = Depends(get_current_user)):
    """Conduct deep research to find competitors and industry info"""
    try:
        from services.deep_research import conduct_deep_research
        
        if not request.brand_name:
             raise HTTPException(status_code=400, detail="Brand name is required")
        
        logger.info(f"🔍 Starting deep research for {request.brand_name}...")
        
        # Run deep research (synchronously for now as per user request flow)
        results = conduct_deep_research(
            brand_name=request.brand_name,
            website_url=request.website_url,
            industry=request.industry,
            custom_competitors=request.custom_competitors
        )
        
        return {
            "status": "success", 
            "data": results
        }
    except Exception as e:
        logger.error(f"Error in deep research endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tools/usage")
async def get_tools_usage(user_id: str = Depends(get_current_user)):
    """Get the tool usage limits for the current user."""
    try:
        from services import tool_usage
        usage = tool_usage.get_user_tool_usage(user_id)
        return {
            "status": "success",
            "usage": usage
        }
    except Exception as e:
        logger.error(f"Error fetching tool usage: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/seo/analyze")
async def analyze_seo(request: SeoAnalysisRequest, user_id: str = Depends(get_current_user)):
    """Run SEO Analysis on a specific URL for selected skills"""
    try:
        from services.seo_analyzer import evaluate_seo_skills
        from services import tool_usage
        
        if not request.url:
             raise HTTPException(status_code=400, detail="URL is required")
        if not request.skills or len(request.skills) == 0:
             raise HTTPException(status_code=400, detail="At least one skill must be selected")
        if len(request.skills) > 1:
             raise HTTPException(status_code=400, detail="A maximum of 1 skill can be selected at a time")
             
        valid_skills = []
        for skill in request.skills:
            if tool_usage.check_seo_skill_limit(user_id, skill):
                valid_skills.append(skill)
        
        if not valid_skills:
            raise HTTPException(status_code=403, detail="You have already used the selected SEO skills. Each skill can only be used once.")
             
        logger.info(f"🔍 Starting SEO Analysis for {request.url} with skills: {valid_skills}")
        
        results = evaluate_seo_skills(
            url=request.url,
            skills=valid_skills,
            max_pages=30,
            user_id=user_id
        )
        
        for skill in valid_skills:
            tool_usage.increment_seo_skill_usage(user_id, skill)
        
        return {
            "status": "success", 
            "data": results
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in SEO analysis endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analysis/run")
async def run_analysis(request: AnalysisRequest, background_tasks: BackgroundTasks, user_id: str = Depends(get_current_user)):
    """Start a new analysis (runs in background)"""
    try:
        # ─── Plan Limit Enforcement ───
        sub_status = get_subscription_status(user_id)
        raw_plan = sub_status.get("subscription_plan", "free") if sub_status else "free"
        plan_name = raw_plan.lower() if raw_plan else "free"
        limits = get_plan_limits_dynamic(raw_plan)

        # If project_id is missing, this is a new brand/project analysis
        if not request.project_id:
            existing_projects = get_user_projects(user_id)
            # Check if a project with this name already exists (case-insensitive)
            brand_exists = any(p['name'].lower() == request.brand_name.lower() for p in existing_projects)
            
            if not brand_exists and len(existing_projects) >= limits["max_projects"]:
                raise HTTPException(
                    status_code=403,
                    detail=f"Project limit reached for your {plan_name.capitalize()} ({limits['max_projects']} max). Please upgrade or delete an existing project."
                )

        custom_keywords = None
        if request.custom_keywords and len(request.custom_keywords) > 0:
            # Clean and validate keywords
            custom_keywords = [k.strip() for k in request.custom_keywords if k.strip()]
            custom_keywords = list(set(custom_keywords))  # Remove duplicates
            if len(custom_keywords) > 20:
                custom_keywords = custom_keywords[:20]
            
            logger.info(f"✅ Custom keywords provided: {custom_keywords}")
        
        # Validate custom competitors if provided
        custom_competitors = None
        if request.custom_competitors and len(request.custom_competitors) > 0:
            # Clean and validate competitor names
            custom_competitors = [c.strip() for c in request.custom_competitors if c.strip()]
            
            # Remove duplicates
            custom_competitors = list(set(custom_competitors))
            
            # Limit to 10 competitors
            if len(custom_competitors) > 10:
                custom_competitors = custom_competitors[:10]
            
            logger.info(f"✅ Custom competitors provided: {custom_competitors}")
        
        # ✅ NEW: Use selected_llms if provided, otherwise empty list (will be selected in cohort selector)
        normalized_llms = []
        if request.selected_llms and len(request.selected_llms) > 0:
            valid_llms = ["Claude", "Mistral", "Google AI Overview"]
            
            for llm in request.selected_llms:
                if isinstance(llm, str):
                    matched = False
                    for valid_llm in valid_llms:
                        if valid_llm.lower() in llm.lower() or llm.lower() in valid_llm.lower():
                            normalized_llms.append(valid_llm)
                            matched = True
                            break
                    
                    if not matched and llm.lower() not in ["string", ""]:
                        normalized_llms.append(llm)
        
        # Create session ID
        session_id = create_session_id(request.brand_name, request.product_name)
        
        # ✅ FIX: Save initial status to DB instead of memory
        # ✅ FIX: Save initial status to DB instead of memory
        save_session(session_id, request.brand_name, user_id, request.product_name, request.website_url, None, None, request.industry, request.project_id, request.brand_aliases)
        update_session_status(session_id, status="running", progress=0, step="Initializing...")
        
        send_signal("analysis_initialized", session_id, {"brand": request.brand_name})
        
        logger.info(f"🚀 Analysis started for {request.brand_name} (Session: {session_id}) by user {user_id}")
        if normalized_llms:
            logger.info(f"   LLMs: {normalized_llms}")
        else:
            logger.info(f"   LLMs: Will be selected in cohort selector")
        if custom_competitors:
            logger.info(f"   Custom Competitors: {custom_competitors}")
        
        # Add background task
        background_tasks.add_task(
            execute_analysis_workflow,
            session_id,
            request.brand_name,
            request.product_name,
            request.industry,
            request.website_url,
            normalized_llms,  # Can be empty list now
            request.regenerate_prompts,
            custom_keywords,
            custom_competitors,
            user_id,
            request.project_id,
            request.brand_aliases
        )
        
        return {
            "session_id": session_id,
            "status": "started",
            "message": f"Analysis started for {request.brand_name}"
        }
    
    except HTTPException as e:
        logger.error(f"❌ Validation error: {str(e.detail)}")
        raise
    except Exception as e:
        logger.error(f"❌ Error starting analysis: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analysis/fork-session")
async def fork_session(
    request: CustomExecutionRequest, 
    background_tasks: BackgroundTasks,
    parent_session_id: Optional[str] = Query(None, description="The ID of the session to copy context from"),
    user_id: str = Depends(get_current_user)
):
    """
    Creates a NEW session based on an old one, but only executes the specific provided prompts.
    This ensures metrics are calculated ONLY for these prompts.
    """
    try:
        if not parent_session_id:
            raise HTTPException(status_code=400, detail="parent_session_id is required")
            
        # 1. Get Parent Session Metadata
        parent_metadata = get_session_metadata(parent_session_id)
        if not parent_metadata:
            raise HTTPException(status_code=404, detail="Parent session not found")
        
        brand_name = parent_metadata['brand_name']
        product_name = parent_metadata.get('product_name')
        
        # 2. Create NEW Session ID
        new_session_id = create_session_id(brand_name, product_name)
        
        # 3. Save New Session
        save_session(
            new_session_id,
            brand_name,
            user_id,
            product_name,
            parent_metadata.get('website_url'),
            parent_metadata.get('research_data'),
            parent_metadata.get('keywords'),
            parent_metadata.get('industry'),
            parent_metadata.get('project_id'),
            parent_metadata.get('brand_aliases')
        )

        # 4. Initialize Status
        update_session_status(new_session_id, status="running", progress=0, step="Queuing Custom Analysis...")
        
        send_signal("analysis_initialized", new_session_id, {"event": "fork_session", "parent_session_id": parent_session_id})

        # ✅ NEW STEP: Duplicate Cohorts & Prompts for the UI
        # Run this immediately so the UI has data when it loads
        duplicate_session_cohorts(parent_session_id, new_session_id)
        duplicate_session_competitors(parent_session_id, new_session_id)
        
        # 5. Start Execution
        if background_tasks:
            background_tasks.add_task(
                execute_prompts_workflow,
                new_session_id,
                request.prompts,
                request.llms
            )
        
        return {
            "success": True, 
            "new_session_id": new_session_id, 
            "message": "New analysis session started"
        }

    except Exception as e:
        logger.error(f"Error forking session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/analysis/execute-custom-prompts/{session_id}")
async def execute_custom_prompts_endpoint(
    session_id: str, 
    request: CustomExecutionRequest, 
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user)
):
    """
    Executes a specific list of raw prompt strings. 
    Used by the Dashboard Prompt Manager tab for re-analysis or custom prompt execution.
    """
    try:
        if not request.prompts:
            raise HTTPException(status_code=400, detail="No prompts provided")
        
        if not request.llms:
             raise HTTPException(status_code=400, detail="No LLMs selected")

        # Verify session ownership
        verify_session_owner(session_id, user_id)
            
        # Update Status to indicate we are starting
        update_session_status(session_id, status="running", progress=0, step="Queuing Custom Analysis...")

        send_signal("analysis_initialized", session_id, {"event": "execute_custom_prompts"})

        logger.info(f"🚀 Custom Execution started for Session {session_id}")
        logger.info(f"   Prompts: {len(request.prompts)}")
        logger.info(f"   LLMs: {request.llms}")

        # Reuse the existing workflow function
        background_tasks.add_task(
            execute_prompts_workflow,
            session_id,
            request.prompts, # Passing raw strings here
            request.llms
        )
        
        return {
            "success": True, 
            "message": "Execution started", 
            "data": {"prompt_count": len(request.prompts)}
        }

    except Exception as e:
        logger.error(f"Error starting custom execution: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/recent-analyses")
def recent_analyses(user_id: str = Depends(get_current_user)):
    try:
        # Get recent sessions for the current user
        recent_sessions = get_user_sessions(user_id)
        # Example format: [{session_id, brand_name, timestamp, product_name, website_url}]
        return {"total": len(recent_sessions), "analyses": recent_sessions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching recent analyses: {str(e)}")
    
@app.get("/api/analysis/status/{session_id}")
async def get_session_status_endpoint(session_id: str, user_id: str = Depends(get_current_user)):
    """Get current analysis progress from database (JWT-protected, session-ownership enforced)"""
    try:
        from services.database_manager import get_session_status

        # IDOR guard: ensure the session belongs to the authenticated user
        verify_session_owner(session_id, user_id)

        status = get_session_status(session_id)
        if not status:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        return status
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching status: {str(e)}")
        raise HTTPException(status_code=500, detail="An internal error occurred")


@app.get("/api/results/{session_id}")
def get_results(session_id: str, user_id: str = Depends(get_current_user)):
    """Get completed analysis results"""
    try:
        from services.database_manager import get_session_results_aggregated, get_session_metadata
        
        # First check if session exists using lightweight metadata query
        session_metadata = get_session_metadata(session_id)
        if not session_metadata:
            logger.error(f"❌ Session not found in database: {session_id}")
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
         
        # Verify user owns this session
        stored_user_id = session_metadata.get('user_id')
        
        # Log IDs for debugging (hide first part for security)
        logger.info(f"🔍 Verifying access: User {str(user_id)[-5:]} vs Session Owner {str(stored_user_id)[-5:]}")
        
        if str(stored_user_id) != str(user_id):
            logger.warning(f"🚫 Access denied for user {user_id} to session {session_id} (Owned by {stored_user_id})")
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Get aggregated results
        logger.info(f"📊 Fetching aggregated results for {session_id}...")
        results = get_session_results_aggregated(session_id)
        if not results:
            logger.warning(f"⏳ No aggregated results found for session {session_id}. Session may still be processing.")
            # Return session metadata with empty results instead of 404
            return {
                'session_id': session_id,
                'brand_name': session_metadata.get('brand_name', 'Unknown'),
                'num_prompts': 0,
                'brand_scores': [],
                'share_of_voice': [],
                'llm_responses': [],
                'domain_citations': [],
                'competitors': [],
                'cohorts': [],
                'created_at': session_metadata.get('timestamp', ''),
                'average_visibility_score': 0,
                'average_position': 0,
                'average_mentions': 0,
                'session_metadata': {
                    'user_id': session_metadata.get('user_id'),
                    'product_name': session_metadata.get('product_name'),
                    'website_url': session_metadata.get('website_url'),
                    'keywords': session_metadata.get('keywords')
                },
                'message': 'Session found but results are still being processed'
            }
        
        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching results: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analysis/citations/{session_id}")
def get_citation_analytics(session_id: str, user_id: str = Depends(get_current_user)):
    """Get detailed citation analytics for a session (IDOR-protected)"""
    try:
        from services.database_manager import get_detailed_citation_analytics

        # IDOR guard: ensure the session belongs to the authenticated user
        verify_session_owner(session_id, user_id)

        results = get_detailed_citation_analytics(session_id)
        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting citation analytics: {str(e)}")
        raise HTTPException(status_code=500, detail="An internal error occurred")

@app.get("/api/analysis/citations/brand/{brand_name}")
def get_brand_citation_analytics(brand_name: str, user_id: str = Depends(get_current_user)):
    """Get aggregated citation analytics for all sessions of a brand"""
    try:
        from services.database_manager import get_brand_citation_repository
        
        # Safe decoding of brand name if it's URL encoded
        from urllib.parse import unquote
        decoded_brand_name = unquote(brand_name)
        
        logger.info(f"📊 Fetching brand-wide citation repository for '{decoded_brand_name}'")
        results = get_brand_citation_repository(decoded_brand_name, user_id)
        return results
    except Exception as e:
        logger.error(f"Error getting brand citation analytics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/results/")
def list_sessions(user_id: str = Depends(get_current_user)):
    """List user's sessions"""
    try:
        from services.database_manager import get_user_sessions
        sessions = get_user_sessions(user_id)
        return {
            "total": len(sessions),
            "sessions": sessions
        }
    except Exception as e:
        logger.error(f"Error listing sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============= PROJECT MANAGEMENT ENDPOINTS =============

@app.post("/api/projects")
async def create_new_project(request: ProjectCreateRequest, user_id: str = Depends(get_current_user)):
    """Create a new project and initialize its monitored entities"""
    try:
        # ─── 1. Limit Enforcement ───────────────────────────────────────────
        # Get subscription status to find limits
        sub_status = get_subscription_status(user_id)
        plan_name = "free"
        if sub_status and sub_status.get("is_active"):
            raw_plan = sub_status.get("subscription_plan", "free")
            plan_name = raw_plan.lower() if raw_plan else "free"
            
        limits = get_plan_limits_dynamic(plan_name)
        
        # Check existing project count
        existing_projects = get_user_projects(user_id)
        if len(existing_projects) >= limits["max_projects"]:
            raise HTTPException(
                status_code=403,
                detail=f"Project limit reached for your {plan_name.capitalize()}. (Max: {limits['max_projects']})"
            )
            
        # Check initial prompts count
        prompts_to_add = request.initial_prompts or []
        if len(prompts_to_add) > limits["max_prompts_per_project"]:
            raise HTTPException(
                status_code=403,
                detail=f"Prompt limit per project exceeded. Your plan allows {limits['max_prompts_per_project']} prompts per project."
            )
            
        # Check initial competitors count
        comps_to_add = request.initial_competitors or []
        if len(comps_to_add) > limits.get("max_competitors", 10):
            raise HTTPException(
                status_code=403,
                detail=f"Competitor limit exceeded. System limits tracking to {limits.get('max_competitors', 10)} competitors maximum."
            )


        # ─── 2. Creation ───────────────────────────────────────────────────
        # 1. Create the project
        project = create_project(
            user_id=user_id,
            name=request.name,
            website_url=request.website_url,
            industry=request.industry,
            update_frequency=request.update_frequency
        )
        
        if not project:
            raise HTTPException(status_code=500, detail="Failed to create project")
        
        project_id = project['id']
        
        # 2. Add initial monitored prompts if provided
        if prompts_to_add:
            add_monitored_prompts(project_id, prompts_to_add)
            
        # 3. Add initial monitored competitors if provided
        if request.initial_competitors:
            add_monitored_competitors(project_id, request.initial_competitors)
            
        return {
            "status": "success",
            "message": "Project created successfully",
            "project": project
        }
    except Exception as e:
        logger.error(f"Error creating project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects")
async def list_projects(user_id: str = Depends(get_current_user)):
    """List all projects for the user"""
    try:
        projects = get_user_projects(user_id)
        return {"projects": projects}
    except Exception as e:
        logger.error(f"Error listing projects: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{project_id}")
async def get_project_details(project_id: str, user_id: str = Depends(get_current_user)):
    """Get detailed project info including monitored entities"""
    try:
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
            
        if project['user_id'] != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
            
        prompts = get_monitored_prompts(project_id)
        competitors = get_monitored_competitors(project_id)
        
        return {
            "project": project,
            "monitored_prompts": prompts,
            "monitored_competitors": competitors
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project details: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/projects/{project_id}")
async def update_project_settings(project_id: str, request: ProjectUpdateRequest, user_id: str = Depends(get_current_user)):
    """Update project configuration"""
    try:
        project = get_project_by_id(project_id)
        if not project or project['user_id'] != user_id:
            raise HTTPException(status_code=404, detail="Project not found or access denied")

        # Validate update_frequency if provided
        from services.database_manager import VALID_FREQUENCIES
        update_data = request.dict(exclude_unset=True)
        if 'update_frequency' in update_data and update_data['update_frequency'] not in VALID_FREQUENCIES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid update_frequency '{update_data['update_frequency']}'. "
                       f"Allowed: {', '.join(sorted(VALID_FREQUENCIES))}"
            )

        # Whitelist: only allow safe fields — never sync_status/sync_started_at
        ALLOWED_FIELDS = {'name', 'website_url', 'industry', 'update_frequency', 'is_active'}
        safe_data = {k: v for k, v in update_data.items() if k in ALLOWED_FIELDS}
        if not safe_data:
            raise HTTPException(status_code=400, detail="No valid fields to update")

        if update_project(project_id, safe_data):
            return {"status": "success", "message": "Project updated"}
        raise HTTPException(status_code=500, detail="Update failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/projects/{project_id}")
async def delete_user_project(project_id: str, user_id: str = Depends(get_current_user)):
    """Delete a project"""
    try:
        project = get_project_by_id(project_id)
        if not project or project['user_id'] != user_id:
            raise HTTPException(status_code=404, detail="Project not found or access denied")
            
        if delete_project(project_id):
            return {"status": "success", "message": "Project deleted"}
        raise HTTPException(status_code=500, detail="Delete failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{project_id}/metrics")
async def get_project_metrics(project_id: str, days: int = Query(30), user_id: str = Depends(get_current_user)):
    """Get historical metrics for the project dashboard"""
    try:
        project = get_project_by_id(project_id)
        if not project or project['user_id'] != user_id:
            raise HTTPException(status_code=404, detail="Project not found or access denied")
            
        metrics = get_project_dashboard_metrics(project_id, days)
        return {"metrics": metrics}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    

# ─── Cron / Webhook endpoint for scheduled analysis ──────────────────────────
@app.post("/api/cron/process-scheduled-projects")
async def cron_process_scheduled_projects(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Trigger the scheduler to process all due projects.
    Protected by HMAC-SHA256 (X-Timestamp + X-Signature headers).
    """
    raw_body = await request.body()
    if not verify_cron_request(dict(request.headers), raw_body):
        raise HTTPException(status_code=401, detail="Unauthorized: invalid or expired signature")

    from services.scheduler import process_due_projects
    background_tasks.add_task(process_due_projects)
    return {"status": "accepted", "message": "Scheduler triggered – processing in background"}


@app.post("/api/analysis/generate-custom-cohort-prompts/{session_id}")
async def generate_custom_cohort_prompts(
    session_id: str,
    request: dict,
    user_id: str = Depends(get_current_user)
):
    """
    Generate prompts for a user-created custom cohort.
    User provides cohort name/description, backend generates 5 prompts.
    """
    try:
        # Verify session exists and belongs to the authenticated user
        session_metadata = verify_session_owner(session_id, user_id)
        
        cohort_name = request.get("cohort_name", "").strip()
        cohort_description = request.get("cohort_description", "").strip()
        
        if not cohort_name:
            raise HTTPException(status_code=400, detail="Cohort name is required")
        
        logger.info(f" Generating prompts for custom cohort: {cohort_name}")
        
        # Get session data for context
        from services.database_manager import get_cohorts_for_session, save_custom_cohort, save_prompts_with_cohorts
        
        brand_name = session_metadata.get('brand_name')
        product_name = session_metadata.get('product_name')  # Correct
        research_data = session_metadata.get('research_data', {})  # Correct
        keywords = session_metadata.get('keywords', [])  # Correct
        industry = session_metadata.get('industry')  # Correct   
        
        # Create cohort dict for prompt generation
        custom_cohort = {
            'name': cohort_name,
            'description': cohort_description or f"Custom cohort focusing on {cohort_name}",
            'prompt_count': 5
        }
        
        # Generate prompts using existing logic
        from services.prompt_generator import generate_prompts_by_cohort
        
        prompts = generate_prompts_by_cohort(
            brand_name=brand_name,
            cohort=custom_cohort,
            research_context=research_data,
            keywords=keywords,
            industry=industry,
            product_name=product_name
        )
        
        # Save custom cohort to database
        existing_cohorts = get_cohorts_for_session(session_id)
        cohort_order = len(existing_cohorts)
        
        cohort_id = save_custom_cohort(
            session_id,
            cohort_name,
            cohort_description or custom_cohort['description'],
            cohort_order
        )
        
        if cohort_id < 0:
            raise HTTPException(status_code=500, detail="Failed to save custom cohort")
        
        # Save generated prompts
        cohort_prompts_data = [{
            'cohort_id': cohort_id,
            'prompts': prompts
        }]
        save_prompts_with_cohorts(session_id, cohort_prompts_data)
        
        logger.info(f" Generated {len(prompts)} prompts for custom cohort '{cohort_name}'")
        
        return {
            "cohort_id": cohort_id,
            "cohort_name": cohort_name,
            "cohort_description": cohort_description,
            "prompts": prompts,
            "message": f"Generated {len(prompts)} prompts for {cohort_name}"
        }
        
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Error generating custom cohort prompts: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/api/analysis/execute-selected-prompts/{session_id}")
async def execute_selected_prompts(
    session_id: str,
    request: dict,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    user_id: str = Depends(get_current_user)
):
    """
    Execute analysis with user-selected/custom cohorts and prompts
    """
    try:
        logger.info(f"📥 Received execute-selected-prompts request for {session_id}: {json.dumps(request)}")
        # Check if session exists in database and belongs to the authenticated user
        session_metadata = verify_session_owner(session_id, user_id)
        
        # ── 1. Plan-Based Limit Enforcement ────────────────────────────────
        session_user_id = session_metadata.get('user_id') or user_id
        sub_status = get_subscription_status(session_user_id) if session_user_id else None
        raw_plan = sub_status.get("subscription_plan", "free") if sub_status else "free"
        plan_name = raw_plan.lower() if raw_plan else "free"
        limits = get_plan_limits_dynamic(raw_plan)
        max_prompts = limits.get("max_prompts_per_project", 5)

        # Extract request data
        selected_cohorts_data = request.get("selected_cohorts", [])
        custom_cohorts_data = request.get("custom_cohorts", [])
        selected_llms = request.get("selected_llms", [])
        
        # Validation
        total_cohorts = len(selected_cohorts_data) + len(custom_cohorts_data)
        
        if total_cohorts == 0:
            logger.warning(f"❌ 400 Validation Error: total_cohorts is 0")
            raise HTTPException(status_code=400, detail="No cohorts selected")
        
        if total_cohorts > 5:
            logger.warning(f"❌ 400 Validation Error: total_cohorts {total_cohorts} > 5")
            raise HTTPException(
                status_code=400,
                detail=f"Maximum 5 cohorts allowed. You selected {total_cohorts}."
            )
            
        # ─── Global Prompt Limit Check ───
        total_selected_prompts = 0
        for c in selected_cohorts_data:
            total_selected_prompts += len(c.get("selected_prompt_indices", []))
            total_selected_prompts += len(c.get("custom_prompts", []))
        
        for cc in custom_cohorts_data:
            total_selected_prompts += len(cc.get("prompts", []))
            
        if total_selected_prompts > max_prompts:
             logger.warning(f"❌ 400 Validation Error: total_selected_prompts ({total_selected_prompts}) > max_prompts ({max_prompts}) for plan {plan_name}")
             raise HTTPException(
                status_code=400,
                detail=f"Prompt limit reached. Your {plan_name.capitalize()} allows total {max_prompts} prompts per project. You selected {total_selected_prompts}."
            )

        if not selected_llms:
            logger.warning(f"❌ 400 Validation Error: selected_llms is empty")
            raise HTTPException(status_code=400, detail="No LLMs selected")
        
        logger.info(f" Processing {total_cohorts} cohorts ({len(selected_cohorts_data)} selected, {len(custom_cohorts_data)} custom)")
        
        # Get generated cohorts for session
        from services.database_manager import (
            get_cohorts_for_session,
            save_custom_cohort,
            save_custom_prompts,
            get_prompt_count_for_cohort
        )
        
        all_cohorts = get_cohorts_for_session(session_id)
        
        # Build final prompt list
        final_prompts = []
        cohort_details = []
        
        # Process SELECTED cohorts
        for cohort_data in selected_cohorts_data:
            cohort_index = cohort_data.get("cohort_index")
            selected_prompt_indices = cohort_data.get("selected_prompt_indices", [])
            custom_prompts = cohort_data.get("custom_prompts", [])
            
            # We've already checked the global total above
            total_prompts_in_cohort = len(selected_prompt_indices) + len(custom_prompts)
            
            if cohort_index < len(all_cohorts):
                cohort = all_cohorts[cohort_index]
                cohort_name = cohort['name']
                cohort_id = cohort['id']
                
                # Add selected generated prompts
                for prompt_idx in selected_prompt_indices:
                    if prompt_idx < len(cohort['prompts']):
                        prompt_text = cohort['prompts'][prompt_idx]['prompt_text']
                        final_prompts.append(prompt_text)
                
                # Add custom prompts if any
                if custom_prompts:
                    # Save custom prompts to database
                    save_custom_prompts(
                        session_id,
                        cohort_id,
                        custom_prompts,
                        start_index=len(cohort['prompts'])
                    )
                    final_prompts.extend(custom_prompts)
                
                cohort_details.append({
                    'type': 'selected',
                    'name': cohort_name,
                    'prompt_count': total_prompts_in_cohort
                })
                
                logger.info(f"   Selected cohort: {cohort_name} ({total_prompts_in_cohort} prompts)")
        
        # Process CUSTOM cohorts
        for idx, custom_cohort in enumerate(custom_cohorts_data):
            cohort_name = custom_cohort.get("name", f"Custom Topic {idx+1}")
            cohort_description = custom_cohort.get("description", "Custom user-defined cohort")
            custom_prompts = custom_cohort.get("prompts", [])
            
            # Already checked global total
            
            # Save custom cohort
            cohort_order = len(all_cohorts) + idx
            custom_cohort_id = save_custom_cohort(
                session_id,
                cohort_name,
                cohort_description,
                cohort_order
            )
            
            if custom_cohort_id > 0:
                # Save custom prompts
                save_custom_prompts(session_id, custom_cohort_id, custom_prompts)
                final_prompts.extend(custom_prompts)
                
                cohort_details.append({
                    'type': 'custom',
                    'name': cohort_name,
                    'prompt_count': len(custom_prompts)
                })
                
                logger.info(f"   Custom cohort: {cohort_name} ({len(custom_prompts)} prompts)")
        
        if not final_prompts:
            raise HTTPException(status_code=400, detail="No prompts to analyze")
        
        logger.info(f" Total prompts to execute: {len(final_prompts)}")
        logger.info(f"   Cohorts breakdown: {cohort_details}")
        
        # Continue analysis in background
        background_tasks.add_task(
            execute_prompts_workflow,
            session_id,
            final_prompts,
            selected_llms
        )
        
        # Update status in database
        update_session_status(session_id, status="running", progress=65)
        
        return {
            "session_id": session_id,
            "status": "executing",
            "total_prompts": len(final_prompts),
            "total_cohorts": total_cohorts,
            "cohort_details": cohort_details,
            "message": f"Executing {len(final_prompts)} prompts across {total_cohorts} cohorts"
        }
        
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Error executing selected prompts: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
        
@app.post("/api/analysis/validate-selection/{session_id}")
async def validate_selection(
    session_id: str,
    request: dict,
    user_id: str = Depends(get_current_user)
):
    """
    Validate user's cohort and prompt selection before execution.
    Returns validation errors if any.
    """
    try:
        # Verify session exists and belongs to the authenticated user
        session_metadata = verify_session_owner(session_id, user_id)
        session_user_id = session_metadata.get('user_id') or user_id
        
        # ─── Plan-Based Validation ───
        sub_status = get_subscription_status(session_user_id) if session_user_id else None
        raw_plan = sub_status.get("subscription_plan", "free") if sub_status else "free"
        plan_name = raw_plan.lower() if raw_plan else "free"
        limits = get_plan_limits_dynamic(raw_plan)
        max_prompts = limits.get("max_prompts_per_project", 5)

        selected_cohorts_data = request.get("selected_cohorts", [])
        custom_cohorts_data = request.get("custom_cohorts", [])
        
        errors = []
        
        # Check total cohorts
        total_cohorts = len(selected_cohorts_data) + len(custom_cohorts_data)
        if total_cohorts > 5:
            errors.append(f"Maximum 5 cohorts allowed. You selected {total_cohorts}.")
        
        if total_cohorts == 0:
            errors.append("Please select at least one cohort.")
        
        # ─── Global Prompt Limit Check ───
        total_selected_prompts = 0
        for c in selected_cohorts_data:
            total_selected_prompts += len(c.get("selected_prompt_indices", []))
            total_selected_prompts += len(c.get("custom_prompts", []))
        
        for cc in custom_cohorts_data:
            total_selected_prompts += len(cc.get("prompts", []))
            
        if total_selected_prompts > max_prompts:
             errors.append(f"Prompt limit reached. Your {plan_name.capitalize()} allows total {max_prompts} prompts per project. You selected {total_selected_prompts}.")

        # Check prompts per cohort (just check for 0)
        for idx, cohort_data in enumerate(selected_cohorts_data):
            selected_count = len(cohort_data.get("selected_prompt_indices", []))
            custom_count = len(cohort_data.get("custom_prompts", []))
            total = selected_count + custom_count
            
            if total == 0:
                errors.append(f"Cohort {idx+1} has no prompts selected.")
                                                                                    
        for idx, custom_cohort in enumerate(custom_cohorts_data):
            prompt_count = len(custom_cohort.get("prompts", []))
            
            if prompt_count == 0:
                errors.append(f"Custom cohort '{custom_cohort.get('name', 'Unnamed')}' has no prompts.")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "total_cohorts": total_cohorts,
            "max_cohorts": 5,
            "max_prompts": max_prompts
        }
        
    except Exception as e:
        logger.error(f"Error validating selection: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/analysis/cohorts/{session_id}")
def get_analysis_cohorts(session_id: str, user_id: str = Depends(get_current_user)):
    """
    Get cohorts and prompts for prompt selection UI
    """
    try:
        from services.database_manager import get_cohorts_for_session
        
        # Verify this session belongs to the current user
        session_response = supabase.table('analysis_sessions').select('user_id').eq('session_id', session_id).execute()
        if not session_response.data or session_response.data[0].get('user_id') != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        cohorts = get_cohorts_for_session(session_id)
        
        # Return empty cohorts list if none found (not a 404, just empty)
        return {
            "session_id": session_id,
            "cohorts": cohorts or [],
            "total_prompts": sum(c['prompt_count'] for c in (cohorts or []))
        }
        
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Error retrieving cohorts: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
# ============= BACKGROUND TASKS =============
async def execute_analysis_workflow(
    session_id: str,
    brand_name: str,
    product_name: Optional[str],
    industry: Optional[str],
    website_url: Optional[str],
    selected_llms: List[str],
    regenerate_prompts: bool = True,
    custom_keywords: Optional[List[str]] = None,
    custom_competitors: Optional[List[str]] = None,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    brand_aliases: Optional[List[str]] = None
):
    """   
    Cohort-based analysis workflow with custom competitor support
    Phase 1: Generate cohorts and prompts, Wait for user selection
    Phase 2: Execute selected prompts (handled by separate function)
    """
    try:
        # Step 1: Deep Research (15%)
        update_progress(session_id, 15, " Conducting market research...")
        logger.info(f"Step 1: Deep Research for {brand_name}")
        
        research_data = conduct_deep_research(
            brand_name, 
            website_url, 
            industry,
            custom_competitors=custom_competitors
        )
        
        # Step 2: Keywords (25%)
        update_progress(session_id, 25, "🔍 Processing keywords...")
        logger.info("Step 2: Keyword Extraction")

        extracted_content = None

        if custom_keywords and len(custom_keywords) > 0:
            keywords = custom_keywords
            logger.info(f"✅ Using {len(keywords)} custom keywords: {keywords}")
        else:
            # ✅ NEW: Try to extract keywords from URL if provided
            if website_url:
                logger.info(f"🌐 No custom keywords provided, extracting from URL: {website_url}")
                url_keywords, extracted_content = await extract_keywords_from_url(website_url, brand_name, num_keywords=40)
                
                if url_keywords and len(url_keywords) > 0:
                    keywords = url_keywords
                    logger.info(f"✅ Extracted {len(keywords)} keywords from URL: {keywords}")
                else:
                    logger.info(f"⚠️ URL extraction failed, falling back to research-based extraction")
                    keywords = extract_keywords(
                        brand_name=brand_name, 
                        research_data=research_data, 
                        product_name=product_name, 
                        industry=industry,
                        num_keywords=20
                    )
                    logger.info(f"✅ Extracted {len(keywords)} keywords from research")
            else:
                logger.info(f"ℹ️ No URL provided, using research-based keyword extraction")
                keywords = extract_keywords(
                    brand_name=brand_name, 
                    research_data=research_data, 
                    product_name=product_name, 
                    industry=industry,
                    num_keywords=20
                )
                logger.info(f"✅ Extracted {len(keywords)} keywords from research")
            
        
        # Step 3: Generate Cohorts (35%)
        update_progress(session_id, 35, " Generating topic cohorts...")
        logger.info("Step 3: Cohort Generation")
        
        from services.cohort_generator import generate_cohorts
        
        num_cohorts = 5
        cohorts = generate_cohorts(
            brand_name=brand_name,
            research_context=research_data,
            keywords=keywords,
            industry=industry,
            num_cohorts=num_cohorts,
            product_name=product_name,
            extracted_content=extracted_content
        )
        
        if not cohorts:
            logger.warning("Cohort generation failed, using fallback")
            cohorts = [
                {'name': 'Brand Discovery', 'description': 'Finding and comparing brands', 'prompt_count': 3},
                {'name': 'Product Reviews', 'description': 'Reviews and ratings', 'prompt_count': 3},
                {'name': 'Buying Decisions', 'description': 'Purchase considerations', 'prompt_count': 3},
                {'name': 'Problem Solving', 'description': 'How-to and troubleshooting', 'prompt_count': 3},
                {'name': 'Industry Trends', 'description': 'Market trends and innovations', 'prompt_count': 3}
            ]
        save_session(session_id, brand_name, user_id, product_name, website_url, research_data, keywords, industry, project_id, brand_aliases)
        # Save cohorts to database
        from services.database_manager import save_cohorts, save_prompts_with_cohorts
        cohort_ids = save_cohorts(session_id, cohorts)
        
        logger.info(f" Generated {len(cohorts)} cohorts:")
        for cohort in cohorts:
            logger.info(f" {cohort['name']}: {cohort.get('prompt_count', 3)} prompts")
        
        # Step 4: Generate Prompts Per Cohort (50%)
        update_progress(session_id, 50, f" Generating prompts for {len(cohorts)} cohorts...")
        logger.info(f"Step 4: Generating cohort-specific prompts")
        
        from services.prompt_generator import generate_prompts_by_cohort
        
        all_prompts = []
        cohort_prompts_data = []
        
        for idx, (cohort, cohort_id) in enumerate(zip(cohorts, cohort_ids)):
            logger.info(f" Generating prompts for cohort: {cohort['name']}")
            
            try:
                
                cohort_prompts = generate_prompts_by_cohort(
                    brand_name=brand_name,
                    cohort=cohort,
                    research_context=research_data,
                    keywords=keywords,
                    industry=industry,
                    product_name=product_name
                )
                
                if cohort_prompts:
                    all_prompts.extend(cohort_prompts)
                    cohort_prompts_data.append({
                        'cohort_id': cohort_id,
                        'prompts': cohort_prompts
                    })
                    logger.info(f" Generated {len(cohort_prompts)} prompts")
                else:
                    logger.warning(f" No prompts generated for cohort: {cohort['name']}")
                    
            except Exception as e:
                logger.error(f" Error generating prompts for cohort {cohort['name']}: {str(e)}")
        
        if not all_prompts:
            raise Exception("Failed to generate any prompts across all cohorts")
        
        # Save prompts with cohort mapping
        save_prompts_with_cohorts(session_id, cohort_prompts_data)
        
        logger.info(f" Generated total {len(all_prompts)} prompts across {len(cohorts)} cohorts")
        
        # Save session metadata
        
        # Extract competitors
        if custom_competitors and len(custom_competitors) > 0:
            competitors_list = custom_competitors
            logger.info(f" Using {len(competitors_list)} custom competitors: {competitors_list}")
        else:
            competitors_list = research_data.get('competitors', [])
            logger.info(f" Extracted {len(competitors_list)} competitors from research: {competitors_list[:5]}")
        
        # Step 5: PAUSE HERE - Wait for user prompt selection
        update_progress(session_id, 60, " Prompts generated - awaiting your selection...")
        
        # ✅ FIX: Update DB instead of global dict
        update_session_status(
            session_id, 
            status="pending_selection",
            step="Ready for prompt selection"
        )
        
        # Note: We don't need to store cohorts/prompts in memory anymore 
        # because they are already saved to Supabase in Step 3 & 4.
        
        logger.info(f" Analysis paused at prompt selection stage for session {session_id}")
        logger.info(f"    Total prompts available: {len(all_prompts)}")
        logger.info(f"    User must now select prompts to continue analysis")
        
    except Exception as e:
        logger.error(f" Error in analysis workflow: {str(e)}", exc_info=True)
        # ✅ FIX: Update DB with error status
        update_session_status(
            session_id, 
            status="error", 
            error=str(e)
        )

async def execute_prompts_workflow(
    session_id: str,
    selected_prompts: List[str],
    selected_llms: List[str]
):
    """
    Phase 2 - Execute LLM analysis on user-selected prompts
    This runs after user selects prompts in the UI
    """
    try:
        logger.info(f" Starting execution of {len(selected_prompts)} selected prompts")
        logger.info(f"    LLMs: {selected_llms}")
        
        # Get session metadata
        from services.database_manager import get_session_results
        session_data = get_session_results(session_id)
        
        if not session_data or 'session' not in session_data:
            raise Exception(f"Session {session_id} not found in database")
        
        session_metadata = session_data.get('session')
        
        # Extract session details
        brand_name = session_metadata['brand_name']
        research_data = session_metadata.get('research_data', {})
        keywords = session_metadata.get('keywords', [])
        brand_aliases = session_metadata.get('brand_aliases', [])
        
        # ✅ FIX: Prefer competitors from the competitors table over research_data
        db_competitors = [c['competitor_name'] for c in session_data.get('competitors', [])]
        if db_competitors:
            competitors_list = db_competitors
        else:
            competitors_list = research_data.get('competitors', [])
        
        logger.info(f" Session context loaded:")
        logger.info(f" Brand: {brand_name}")
        logger.info(f" Keywords: {len(keywords)}")
        logger.info(f" Competitors: {len(competitors_list)}")
        
        # Step 6: Execute LLMs (70%)
        update_progress(session_id, 70, f" Running {len(selected_llms)} LLMs on {len(selected_prompts)} prompts...")
        logger.info(f"Step 6: Executing LLMs: {selected_llms}")
        
        llm_responses = execute_prompts_multi_llm_sync(
            prompts=selected_prompts,
            llms=selected_llms,
            brand_name=brand_name
        )
        
        if not llm_responses:
            raise Exception("No LLM responses received")
        
        logger.info(f" Received {len(llm_responses)} LLM responses")
        
        # Step 7: Scoring (85%)
        update_progress(session_id, 85, " Calculating visibility scores...")
        logger.info("Step 7: Scoring")
        
        scored_results = calculate_scores(llm_responses, brand_name, keywords, competitors=competitors_list, brand_aliases=brand_aliases)
        
        logger.info(f" Scored {len(scored_results)} results")
        
        # Save LLM responses WITH CITATIONS to database
        logger.info(" Saving LLM responses and citations to database...")
        saved_count = 0
        
        for result in scored_results:
            try:
                prompt_id = create_prompt_id(session_id, result.get('prompt_index', 0))
                
                # Extract citations and prompt from the original llm_responses
                matching_response = next(
                    (r for r in llm_responses 
                    if r.get('prompt_index') == result.get('prompt_index') 
                    and r.get('llm_name') == result.get('llm_name')),
                    None
                )
                
                citations = matching_response.get('citations', []) if matching_response else []
                prompt_text = matching_response.get('prompt', '') if matching_response else result.get('prompt', '')
                
                # Save LLM response with citations
                save_llm_response(
                    prompt_id, 
                    session_id, 
                    result.get('llm_name'),
                    prompt_text,
                    result.get('response', ''),
                    citations=citations
                )
                
                # Ensure visibility score is in scores dict
                scores_dict = result.get('scores', {})
                if 'normalized_visibility' not in scores_dict and 'visibility_score' in result:
                    scores_dict['normalized_visibility'] = result.get('visibility_score', 0)
                
                # Save scoring results
                save_scoring_result(
                    prompt_id, 
                    session_id, 
                    result.get('llm_name'),
                    scores_dict
                )
                
                saved_count += 1
                
            except Exception as e:
                logger.warning(f" Could not save response: {str(e)}")
        
        logger.info(f" Saved {saved_count}/{len(scored_results)} responses to database")
        
        # Step 8: Share of Voice (95%)
        update_progress(session_id, 95, " Computing share of voice...")
        logger.info("Step 8: Share of Voice")
        
        sov_data = None
        
        # Filter out the main brand from competitors list
        if competitors_list:
            cleaned_competitors = [
                c for c in competitors_list 
                if c.lower().strip() != brand_name.lower().strip()
            ]
            
            if cleaned_competitors:
                try:
                    logger.info(f"Found {len(cleaned_competitors)} competitors (excluding main brand): {cleaned_competitors}")
                    save_competitors(session_id, cleaned_competitors)
                    
                    # Calculate Share of Voice
                    sov_data = calculate_share_of_voice(scored_results, cleaned_competitors, brand_aliases)
                    
                    if sov_data and 'ranked_brands' in sov_data:
                        ranked_brands = sov_data.get('ranked_brands', [])
                        logger.info(f"Saving SOV for {len(ranked_brands)} brands")
                        
                        for rank_index, brand_data in enumerate(ranked_brands, 1):
                            try:
                                brand_name_sov = brand_data.get('brand_name', 'Unknown')
                                sov_scores_dict = {
                                    'normalized_visibility': float(brand_data.get('normalized_visibility', 0)),
                                    'average_positioning': float(brand_data.get('average_positioning', 0)),
                                    'weighted_score': float(brand_data.get('weighted_score', 0)),
                                    'total_mentions': int(brand_data.get('total_mentions', 0))
                                }
                                
                                save_share_of_voice(
                                    session_id,
                                    brand_name_sov,
                                    sov_scores_dict,
                                    rank_index
                                )
                                logger.info(f"  âœ” Saved SOV for {brand_name_sov} (Rank {rank_index})")
                            except Exception as e:
                                logger.warning(f"Could not save SOV for {brand_data.get('brand_name', 'Unknown')}: {str(e)}")
                        
                        logger.info(f" Share of Voice saved: {len(ranked_brands)} brands")
                    else:
                        logger.warning(" ï¸ Share of Voice missing 'ranked_brands' key")
                        
                except Exception as e:
                    logger.error(f" Error calculating Share of Voice: {str(e)}", exc_info=True)
                    sov_data = None
            else:
                logger.info(" ï¸  Competitor list empty after removing main brand.")
                sov_data = None
        else:
            logger.info(" ï¸  No competitors found - skipping Share of Voice")
            sov_data = None
        
        # Aggregate results
        summary = aggregate_results(scored_results)
        save_brand_score_summary(session_id, brand_name, summary)
        
        # Step 9: Complete (100%)
        update_progress(session_id, 100, " Analysis complete!")
        
        send_signal("prompts_executed", session_id, {
            "brand": brand_name,
            "prompts_count": len(selected_prompts),
            "llms_count": len(selected_llms)
        })
        
        # ✅ FIX: Update DB to completed
        update_session_status(
            session_id, 
            status="completed",
            progress=100,
            step="Analysis complete!"
        )

        # ─── Record daily metrics for trend analytics ─────────────────────
        try:
            agg = record_daily_metrics(session_id)
            logger.info(f" Daily metrics recorded: {agg}")
        except Exception as agg_err:
            logger.warning(f" Could not record daily metrics (non-fatal): {agg_err}")
        # ──────────────────────────────────────────────────

        # ─── Sync monitored_prompts with user's selected prompts ─────────────
        # When a user manually selects prompts in the UI, sync them to monitored_prompts.
        # Scheduled runs (is_scheduled=True) do NOT overwrite, ensuring the user's
        # manual selection remains locked in until the user edits them again.
        try:
            _project_id = session_metadata.get("project_id")
            _research_data = session_metadata.get("research_data") or {}
            _is_scheduled = _research_data.get("is_scheduled", False)

            if _project_id and selected_prompts and not _is_scheduled:
                from services.database_manager import add_monitored_prompts as _add_mp, supabase as _sb
                _sb.table("monitored_prompts").delete().eq("project_id", _project_id).execute()
                _add_mp(_project_id, selected_prompts)
                logger.info(
                    f" Synced {len(selected_prompts)} user-selected prompts into "
                    f"monitored_prompts for project {_project_id}"
                )
        except Exception as _sync_err:
            logger.warning(f" Could not sync monitored_prompts (non-fatal): {_sync_err}")
        # ────────────────────────────────────────────────────────────────────

        logger.info(f" Analysis completed for {brand_name}")
        logger.info(f"   - Selected Prompts: {len(selected_prompts)}")
        logger.info(f"   - LLM Responses: {len(llm_responses)}")
        logger.info(f"   - Scored Results: {len(scored_results)}")
        logger.info(f"   - Share of Voice: {'Yes' if sov_data else 'No'}")
        
    except Exception as e:
        logger.error(f"❌ Error in prompt execution workflow: {str(e)}", exc_info=True)
        # ✅ FIX: Preserve selected prompts/cohorts on error so user can re-try without losing selected prompts
        update_session_status(
            session_id, 
            status="pending_selection", 
            error=f"Execution error: {str(e)}. Your selected prompts are preserved — click Run Analysis to retry."
        )

def update_progress(session_id: str, progress: int, step: str):
    """
    Update analysis progress in the database (Stateless)
    """
    # ✅ FIX: Use DB function instead of global dict
    update_session_status(
        session_id, 
        progress=progress, 
        step=step,
        status="running" 
    )
    logger.info(f"[{session_id}] {progress}% - {step}")
from services.database_manager import get_brand_visibility_history

@app.get("/api/brand-history/{brand_name}")
async def get_brand_history(brand_name: str, user_id: str = Depends(get_current_user)):
    """
    Get brand visibility history across all analysis dates (scoped to current user)
    """
    try:
        history = get_brand_visibility_history(brand_name, user_id)
        
        if not history:
            raise HTTPException(
                status_code=404,
                detail=f"No analysis history found for brand: {brand_name} (user)")
        
        return {
            "brand_name": brand_name,
            "history": history,
            "total_analyses": len(history)
        }
    except Exception as e:
        logger.error(f"Error fetching brand history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/brands")
def get_all_brands(user_id: str = Depends(get_current_user)):
    """Get unique brands for the authenticated user only (tenant-scoped)"""
    try:
        brands = get_all_unique_brands(user_id=user_id)
        return {"brands": brands}
    except Exception as e:
        logger.error(f"Error fetching brands: {str(e)}")
        return {"brands": [], "error": "An internal error occurred"}

@app.get("/api/recent-analyses-by-brand/{brand_name}")
def get_recent_analyses_by_brand(brand_name: str, user_id: str = Depends(get_current_user), limit: int = 20):
    """Get recent analyses for a specific brand (tenant-scoped to authenticated user)"""
    try:
        sessions = get_recent_sessions_by_brand(brand_name, limit, user_id=user_id)
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"Error fetching analyses for brand {brand_name}: {str(e)}")
        return {"sessions": [], "error": "An internal error occurred"}
@app.get("/api/visibility-history/brand-product/{brand_name}/{product_name}")
def get_brand_product_history(brand_name: str, product_name: str, user_id: str = Depends(get_current_user)):
    """Get visibility history for brand + product combination (scoped to current user)"""
    try:
        history = get_product_specific_visibility_history(brand_name, product_name, user_id)
        return {"history": history}
    except Exception as e:
        logger.error(f"Error fetching product visibility history: {str(e)}")
        return {"history": [], "error": str(e)}
    
def get_llm_names_from_session(session_id: str) -> List[str]:
    """Get LLM names used in a session - using Supabase"""
    try:
        response = supabase.table('llm_responses').select('llm_name').eq('session_id', session_id).execute()
        llm_names = list(set(row['llm_name'] for row in response.data))
        return llm_names
    except Exception as e:
        logger.error(f"Error getting LLM names: {str(e)}")
        return []
    
@app.post("/api/reanalyze-with-same-prompts/{session_id}")
async def reanalyze_with_same_prompts(
    session_id: str,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user)
):
    """Re-analyze with the same prompts from a previous session"""
    try:
        # Get original session details
        original_session = get_session_results(session_id)
        if not original_session:
            raise HTTPException(status_code=404, detail="Original session not found")
        
        session_metadata = original_session.get('session')
        if not session_metadata:
            raise HTTPException(status_code=404, detail="Original session metadata not found")
        
        # Extract metadata
        brand_name = session_metadata['brand_name']
        product_name = session_metadata.get('product_name')
        website_url = session_metadata.get('website_url')
        research_data = session_metadata.get('research_data', {})
        research_data = session_metadata.get('research_data', {})
        keywords = session_metadata.get('keywords', [])
        brand_aliases = session_metadata.get('brand_aliases', [])
        
        # Get prompts and LLMs
        prompts = get_saved_prompts_for_analysis(session_id)
        llm_names = get_llm_names_from_session(session_id)
        
        if not prompts:
            raise HTTPException(status_code=400, detail="No prompts found for this session")
        if not llm_names:
            logger.warning("No LLM names found in original session, defaulting to Claude")
            llm_names = ['Claude']
        
        # Create new session ID
        new_session_id = create_session_id(brand_name, product_name)
        
        # Save new session (use keyword args to ensure correct mapping)
        save_session(
            new_session_id,
            brand_name,
            user_id=user_id,
            product_name=product_name,
            website_url=website_url,
            research_data=research_data,
            keywords=keywords,
            industry=session_metadata.get('industry'),
            project_id=session_metadata.get('project_id'),
            brand_aliases=brand_aliases
        )
        
        # Initialize progress tracking in database
        update_session_status(new_session_id, status="running", progress=0, step="Initializing Re-analysis...")
        
        # ✅ NEW: Carry forward competitors
        duplicate_session_competitors(session_id, new_session_id)
        
        # Run analysis with saved prompts
        background_tasks.add_task(
            run_analysis_with_saved_prompts,
            new_session_id,
            brand_name,
            prompts,
            llm_names,
            research_data,
            keywords,
            brand_aliases
        )
        
        return {
            "new_session_id": new_session_id,
            "message": "Re-analysis started with same prompts",
            "status": "processing"
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error in re-analysis: {str(e)}", exc_info=True)
        if 'new_session_id' in locals():
            update_session_status(new_session_id, status="error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    
async def run_analysis_with_saved_prompts(
    session_id: str,
    brand_name: str,
    prompts: list,
    llm_names: list,
    research_data: Optional[dict] = None,
    keywords: Optional[list] = None,
    brand_aliases: Optional[list] = None
):
    """Execute analysis using pre-saved prompts"""
    update_progress(session_id, 10, " Re-executing LLMs with saved prompts...")
    try:
        if not research_data:
            research_data = {}
        if not keywords:
            keywords = []
            
        competitors_list = [] # Will check database first
        product_name = research_data.get('product_name')
        
        # If no competitors in research_data, check database
        if not competitors_list:
            logger.warning(" ï¸ No competitors in research_data, checking database...")
            try:
                response = supabase.table('competitors').select('competitor_name').eq('session_id', session_id).order('rank').limit(10).execute()
                
                if response.data:
                    competitors_list = [row['competitor_name'] for row in response.data]
                    logger.info(f" Found {len(competitors_list)} competitors from database: {competitors_list}")
                else:
                    logger.warning(f" ï¸ No competitors found in database for session: {session_id}")
            except Exception as e:
                logger.error(f"Error querying database for competitors: {str(e)}")
        if not competitors_list:
            competitors_list = research_data.get('competitors', [])
            
        logger.info(f" Final data - Competitors: {len(competitors_list)}, Keywords: {len(keywords)}")
        # Step 1: Execute prompts with multiple LLMs
        llm_responses = execute_prompts_multi_llm_sync(
            prompts=prompts,
            llms=llm_names,
            brand_name=brand_name
        )
        if not llm_responses:
            raise Exception("No LLM responses received in re-analysis")
        update_progress(session_id, 60, " Recalculating scores...")
        # Step 2: Calculate scores
        scored_results = calculate_scores(llm_responses, brand_name, keywords, competitors=competitors_list, brand_aliases=brand_aliases)
        # Step 3: Save LLM responses and scores
        for result in scored_results:
            prompt_index = result.get('prompt_index', 0)
            prompt_id = create_prompt_id(session_id, prompt_index)
            matching_response = next(
                (r for r in llm_responses
                if r.get('prompt_index') == prompt_index
                and r.get('llm_name') == result.get('llm_name')),
                None
            )
            citations = matching_response.get('citations', []) if matching_response else []
            prompt_text = matching_response.get('prompt', '') if matching_response else result.get('prompt', '')
            save_llm_response(
                prompt_id,
                session_id,
                result.get('llm_name'),
                prompt_text,
                result.get('response', ''),
                citations=citations
            )
            save_scoring_result(
                prompt_id,
                session_id,
                result.get('llm_name'),
                result.get('scores', {})
            )
        logger.info(f" Saving {len(prompts)} prompts for re-analysis session {session_id}")
        try:
            from services.database_manager import save_prompts_to_db
            save_prompts_to_db(brand_name, prompts, product_name)
            logger.info(f" Prompts saved successfully for brand: {brand_name}")
        except Exception as e:
            logger.warning(f"Could not save prompts for re-analysis: {str(e)}")
        update_progress(session_id, 80, " Computing Share of Voice...")
        # Step 4: Share of Voice
        if competitors_list:
            try:
                save_competitors(session_id, competitors_list)
                logger.info(f" Saved {len(competitors_list)} competitors for session {session_id}")
                sov_data = calculate_share_of_voice(scored_results, competitors_list, brand_aliases)
                if sov_data and 'ranked_brands' in sov_data:
                    logger.info(f" Saving Share of Voice for {len(sov_data['ranked_brands'])} brands in session {session_id}")
                    for rank_index, brand_data in enumerate(sov_data['ranked_brands'], 1):
                        sov_scores_dict = {
                            'normalized_visibility': float(brand_data.get('normalized_visibility', 0)),
                            'average_positioning': float(brand_data.get('average_positioning', 0)),
                            'weighted_score': float(brand_data.get('weighted_score', 0)),
                        }
                        save_share_of_voice(
                            session_id,
                            brand_data.get('brand_name', 'Unknown'),
                            sov_scores_dict,
                            rank_index
                        )
                    logger.info(f" Share of Voice calculation complete for session {session_id}")
                else:
                    logger.warning(f" ï¸ No SOV data generated for session {session_id}")
            except Exception as e:
                logger.error(f" Error calculating Share of Voice in re-analysis: {str(e)}", exc_info=True)
        else:
            logger.info(f"â„¹ï¸ No competitors provided for session {session_id} - skipping Share of Voice calculation")
        # Step 5: Aggregate results
        update_progress(session_id, 90, " Aggregating results...")
        summary = aggregate_results(scored_results)
        save_brand_score_summary(session_id, brand_name, summary)
        # Step 6: Complete
        update_progress(session_id, 100, " Re-analysis complete!")
        logger.info(f" Re-analysis completed for session {session_id}")
    except Exception as e:
        logger.error(f" Error during re-analysis execution for {session_id}: {str(e)}", exc_info=True)
        # ✅ FIX: Update DB
        update_session_status(session_id, status="error", error=str(e))
        
@app.get("/api/same-prompts-history/{session_id}")
def get_same_prompts_history(session_id: str, user_id: str = Depends(get_current_user)):
    """Get visibility history for when same prompts are analyzed again"""
    try:
        from services.database_manager import get_session_results_aggregated
        
        original_results = get_session_results_aggregated(session_id)
        if not original_results:
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Verify this session belongs to the current user
        session_user_id = original_results.get('session_metadata', {}).get('user_id')
        if session_user_id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        brand_name = original_results.get('brand_name')
        product_name = original_results.get('product_name', '')
        
        if not brand_name:
            logger.error(f"No brand_name found in session {session_id}")
            return {"history": [], "error": "Brand name not found"}
        
        logger.info(f" Fetching same prompts history for brand: {brand_name}, session: {session_id}")
        
        # Get saved prompts
        prompts = get_saved_prompts_for_analysis(session_id)
        if not prompts:
            logger.info(f"No prompts found for session {session_id}")
            return {"history": [], "message": "No prompts found"}
        
        logger.info(f"Found {len(prompts)} prompts for matching")
        
        # Get history — scoped to authenticated user so cross-tenant sessions are invisible
        history = get_visibility_history_for_same_prompts(brand_name, product_name, prompts, user_id=user_id)
        
        logger.info(f" Returning {len(history)} data points for same prompts history")
        return {"history": history}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching same prompts history: {str(e)}", exc_info=True)
        return {"history": [], "error": str(e)}

@app.post("/api/analysis/{session_id}/update-competitors")
async def update_competitors_and_recalculate(
    session_id: str,
    request: CompetitorUpdateRequest,
    user_id: str = Depends(get_current_user)
):
    try:
        sub_status = get_subscription_status(user_id) if user_id else None
        raw_plan = sub_status.get("subscription_plan", "free") if sub_status else "free"
        limits = get_plan_limits_dynamic(raw_plan)
        max_competitors = limits.get("max_competitors", 10)
        new_competitors = list(set([c.strip() for c in request.competitors if c.strip()]))
        
        if len(new_competitors) > max_competitors:
             raise HTTPException(
                status_code=400,
                detail=f"Competitor limit reached. You are only allowed to track up to {max_competitors} competitors."
            )

        # 0. Verify session ownership
        verify_session_owner(session_id, user_id)
            
        # 1. Update Competitors
        replace_session_competitors(session_id, new_competitors)
        
        # 2. Get Session Data
        session_results = get_session_results(session_id)
        if not session_results: raise HTTPException(status_code=404, detail="Session not found")
        
        # 3. Clear Old Metrics & Re-Score
        clear_session_metrics(session_id)
        
        formatted_responses = []
        for row in session_results.get('responses', []):
            formatted_responses.append({
                'prompt': row.get('prompt_text'),
                'response': row.get('response_text'),
                'llm_name': row.get('llm_name'),
                'prompt_index': int(row.get('prompt_id').split('_')[-1]) if '_' in row.get('prompt_id') else 0,
                'citations': row.get('citations', [])
            })

        brand_aliases = session_results['session'].get('brand_aliases', [])
        scored_results = calculate_scores(
            formatted_responses, 
            session_results['session']['brand_name'], 
            session_results['session']['keywords'], 
            competitors=new_competitors,
            brand_aliases=brand_aliases
        )

        # 4. Save New Scores
        for result in scored_results:
            prompt_id = create_prompt_id(session_id, result.get('prompt_index', 0))
            save_scoring_result(prompt_id, session_id, result.get('llm_name'), result.get('scores', {}))

        # 5. Recalculate Share of Voice
        if new_competitors:
             sov_data = calculate_share_of_voice(scored_results, new_competitors, brand_aliases=brand_aliases)
             if sov_data and 'ranked_brands' in sov_data:
                for rank, brand in enumerate(sov_data['ranked_brands'], 1):
                    save_share_of_voice(
                        session_id, brand['brand_name'], 
                        {'normalized_visibility': brand['normalized_visibility'], 
                         'average_positioning': brand['average_positioning'], 
                         'weighted_score': brand['weighted_score']}, 
                        rank
                    )

        # 6. Update Summary
        summary = aggregate_results(scored_results)
        save_brand_score_summary(session_id, session_results['session']['brand_name'], summary)
        
        return {"success": True, "competitor_count": len(new_competitors)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in recalculation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============= PROJECT MANAGEMENT ENDPOINTS =============

@app.delete("/api/projects/{project_id}")
def delete_project_endpoint(project_id: str, user_id: str = Depends(get_current_user)):
    """Delete a project and all its data"""
    try:
        # Verify ownership
        project = get_project_by_id(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        
        # Ensure the user owns the project
        if str(project['user_id']) != str(user_id):
            raise HTTPException(status_code=403, detail="Not authorized to delete this project")
            
        success = delete_project(project_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete project")
            
        return {"status": "success", "message": "Project deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# ============= LLMS.TXT GENERATOR ENDPOINTS =============

from services.llms_txt_generator import generate_llms_txt

class LlmsTxtRequest(BaseModel):
    url: str

# In-memory store for llms.txt generation tasks
llms_txt_tasks: Dict = {}

@app.post("/api/llms-txt/generate")
async def generate_llms_txt_endpoint(request: LlmsTxtRequest, background_tasks: BackgroundTasks, user_id: str = Depends(get_current_user)):
    """Start llms.txt generation for a website URL"""
    try:
        from services import tool_usage
        if not tool_usage.check_llms_txt_limit(user_id):
            raise HTTPException(status_code=403, detail="You have reached the limit of 2 llms.txt generations.")

        if not request.url or not request.url.strip():
            raise HTTPException(status_code=400, detail="URL is required")
        
        tool_usage.increment_llms_txt_usage(user_id)
        
        # Create a unique task ID
        import uuid
        task_id = str(uuid.uuid4())
        
        # Initialize task state
        llms_txt_tasks[task_id] = {
            "status": "running",
            "progress": 0,
            "step": "Initializing...",
            "url": request.url,
            "result": None,
            "error": None,
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat()
        }
        
        def progress_callback(progress: int, step: str):
            if task_id in llms_txt_tasks:
                llms_txt_tasks[task_id]["progress"] = progress
                llms_txt_tasks[task_id]["step"] = step
        
        def run_generation(tid: str, url: str, uid: str):
            try:
                result = generate_llms_txt(url, progress_callback=progress_callback, user_id=uid)
                if tid in llms_txt_tasks:
                    llms_txt_tasks[tid]["status"] = "completed"
                    llms_txt_tasks[tid]["progress"] = 100
                    llms_txt_tasks[tid]["step"] = "Generation complete!"
                    llms_txt_tasks[tid]["result"] = result
                # Signal success to Paid.ai
                send_signal("llms_txt_generated", tid, {
                    "url": url,
                    "domain": result.get("domain", ""),
                    "pages_included": result.get("stats", {}).get("pages_included", 0),
                })
            except Exception as e:
                logger.error(f"llms.txt generation error: {str(e)}")
                if tid in llms_txt_tasks:
                    llms_txt_tasks[tid]["status"] = "error"
                    llms_txt_tasks[tid]["error"] = str(e)
                    llms_txt_tasks[tid]["step"] = f"Error: {str(e)}"
                send_signal("llms_txt_error", tid, {"url": url, "error": str(e)})
        
        background_tasks.add_task(run_generation, task_id, request.url.strip(), user_id)
        
        send_signal("llms_txt_started", task_id, {"url": request.url, "user_id": user_id})
        logger.info(f"🚀 llms.txt generation started for {request.url} (Task: {task_id}) by user {user_id}")
        
        return {
            "status": "success",
            "task_id": task_id,
            "message": "llms.txt generation started"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting llms.txt generation: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/llms-txt/status/{task_id}")
async def get_llms_txt_status(task_id: str, user_id: str = Depends(get_current_user)):
    """Get the status of an llms.txt generation task"""
    task = llms_txt_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # Verify ownership
    if task.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    
    response = {
        "status": task["status"],
        "progress": task["progress"],
        "step": task["step"],
        "url": task["url"],
    }
    
    if task["status"] == "completed" and task["result"]:
        response["result"] = task["result"]
    elif task["status"] == "error":
        response["error"] = task["error"]
    
    return response

# Mount Admin Router
from services.admin_routes import router as admin_router
app.include_router(admin_router)

# ============= RUN SERVER =============
if __name__ == "__main__":
    import uvicorn
    
    # Dynamic configuration with production defaults
    host = os.environ.get("BACKEND_HOST", "0.0.0.0")
    port = int(os.environ.get("BACKEND_PORT", 8000))
    is_reload = os.environ.get("RELOAD", "True").lower() == "true"

    print("\n" + "="*60)
    print(f" BRAND VISIBILITY ANALYZER - BACKEND ({host}:{port})")
    print("="*60)
    
    uvicorn.run(
        "app:app",
        host=host, 
        port=port,
        reload=is_reload,
        log_level="info"
    )
-- ==============================================================================
-- GEO PLATFORM - COMPLETE DATABASE SCHEMA FOR STAGING / TEST ENVIRONMENT
-- ==============================================================================
-- Paste this entire script into your Supabase SQL Editor:
-- https://supabase.com/dashboard/project/<staging-project-id>/sql
-- ==============================================================================

-- 1. Enable UUID Extension (standard in Supabase)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ------------------------------------------------------------------------------
-- TABLE: users
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    is_verified BOOLEAN DEFAULT FALSE,
    verification_otp TEXT,
    subscription_plan TEXT DEFAULT 'free',
    billing_cycle TEXT,
    subscription_status TEXT DEFAULT 'inactive',
    subscription_start TIMESTAMPTZ,
    subscription_end TIMESTAMPTZ,
    razorpay_payment_id TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ------------------------------------------------------------------------------
-- TABLE: payment_transactions (Immutable audit ledger)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    user_email TEXT,
    razorpay_order_id TEXT,
    razorpay_payment_id TEXT UNIQUE NOT NULL,
    razorpay_signature TEXT,
    plan_name TEXT,
    billing_cycle TEXT,
    status TEXT DEFAULT 'verified',
    subscription_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_user ON payment_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_transactions_payment_id ON payment_transactions(razorpay_payment_id);

-- ------------------------------------------------------------------------------
-- TABLE: projects
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    website_url TEXT,
    industry TEXT,
    logo_url TEXT,
    country TEXT,
    city TEXT,
    update_frequency TEXT DEFAULT '24h',
    is_active BOOLEAN DEFAULT FALSE,
    sync_status TEXT NOT NULL DEFAULT 'idle',
    sync_started_at TIMESTAMPTZ,
    last_sync_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_projects_scheduler ON projects(is_active, sync_status, last_sync_at);

-- ------------------------------------------------------------------------------
-- TABLE: monitored_prompts
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS monitored_prompts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    prompt_text TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_monitored_prompts_project ON monitored_prompts(project_id);

-- ------------------------------------------------------------------------------
-- TABLE: monitored_competitors
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS monitored_competitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_monitored_competitors_project ON monitored_competitors(project_id);

-- ------------------------------------------------------------------------------
-- TABLE: daily_brand_metrics (Real-time & Historical Dashboard Source)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS daily_brand_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    llm_name TEXT NOT NULL,
    date DATE NOT NULL DEFAULT CURRENT_DATE,
    visibility_score REAL NOT NULL DEFAULT 0,
    avg_position REAL,
    mention_count INTEGER NOT NULL DEFAULT 0,
    total_prompts INTEGER NOT NULL DEFAULT 0,
    citation_count INTEGER DEFAULT 0,
    UNIQUE(project_id, llm_name, date)
);

CREATE INDEX IF NOT EXISTS idx_daily_brand_metrics_proj_date ON daily_brand_metrics(project_id, date);

-- ------------------------------------------------------------------------------
-- TABLE: analysis_sessions
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysis_sessions (
    session_id TEXT PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    brand_name TEXT NOT NULL,
    product_name TEXT,
    industry TEXT,
    website_url TEXT,
    timestamp TEXT NOT NULL,
    research_data JSONB,
    keywords JSONB,
    brand_aliases JSONB,
    status TEXT DEFAULT 'pending',
    current_step TEXT,
    progress INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_analysis_sessions_user ON analysis_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_analysis_sessions_project ON analysis_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_analysis_sessions_brand ON analysis_sessions(brand_name);

-- ------------------------------------------------------------------------------
-- TABLE: cohorts
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cohorts (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id) ON DELETE CASCADE,
    cohort_name TEXT NOT NULL,
    cohort_description TEXT,
    prompt_count INTEGER,
    cohort_order INTEGER,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cohorts_session ON cohorts(session_id);

-- ------------------------------------------------------------------------------
-- TABLE: prompts_cohort_mapping
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prompts_cohort_mapping (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id) ON DELETE CASCADE,
    cohort_id INTEGER NOT NULL REFERENCES cohorts(id) ON DELETE CASCADE,
    prompt_text TEXT NOT NULL,
    prompt_index INTEGER,
    selected BOOLEAN DEFAULT FALSE,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompts_cohort_session ON prompts_cohort_mapping(session_id);
CREATE INDEX IF NOT EXISTS idx_prompts_cohort_id ON prompts_cohort_mapping(cohort_id);

-- ------------------------------------------------------------------------------
-- TABLE: llm_responses
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS llm_responses (
    id SERIAL PRIMARY KEY,
    prompt_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    llm_name TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    citations JSONB,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_responses_session ON llm_responses(session_id);
CREATE INDEX IF NOT EXISTS idx_llm_responses_prompt ON llm_responses(prompt_id);

-- ------------------------------------------------------------------------------
-- TABLE: scoring_results
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scoring_results (
    id SERIAL PRIMARY KEY,
    prompt_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    llm_name TEXT NOT NULL,
    brand_mention_score REAL,
    position_score REAL,
    description_richness_score REAL,
    keyword_strength_score REAL,
    total_score REAL,
    normalized_visibility REAL,
    average_positioning REAL,
    weighted_score REAL,
    brand_position INTEGER,
    total_items INTEGER,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scoring_results_session ON scoring_results(session_id);

-- ------------------------------------------------------------------------------
-- TABLE: competitors
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS competitors (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id) ON DELETE CASCADE,
    competitor_name TEXT NOT NULL,
    rank INTEGER
);

CREATE INDEX IF NOT EXISTS idx_competitors_session ON competitors(session_id);

-- ------------------------------------------------------------------------------
-- TABLE: share_of_voice
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS share_of_voice (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id) ON DELETE CASCADE,
    brand_name TEXT NOT NULL,
    normalized_visibility REAL,
    average_positioning REAL,
    weighted_score REAL,
    rank INTEGER,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_share_of_voice_session ON share_of_voice(session_id);

-- ------------------------------------------------------------------------------
-- TABLE: saved_prompts
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS saved_prompts (
    id SERIAL PRIMARY KEY,
    brand_name TEXT NOT NULL,
    product_name TEXT,
    prompts_json JSONB NOT NULL,
    timestamp TEXT NOT NULL,
    UNIQUE(brand_name, product_name)
);

CREATE INDEX IF NOT EXISTS idx_saved_prompts_brand ON saved_prompts(brand_name);

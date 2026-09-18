-- ==============================================================================
-- GEO PLATFORM - ADMIN PANEL DATABASE MIGRATION
-- ==============================================================================
-- Paste this entire script into your Supabase SQL Editor:
-- https://supabase.com/dashboard/project/<project-id>/sql
-- ==============================================================================

-- 1. Add Admin & Credit columns to `users` table
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'user';             -- 'user' | 'admin' | 'super_admin'
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS credits_remaining INTEGER DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS credits_total INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_is_suspended ON users(is_suspended);

-- 2. Add refund tracking column to `payment_transactions` table
ALTER TABLE payment_transactions ADD COLUMN IF NOT EXISTS refund_id TEXT;

-- 3. Create `admin_audit_logs` table (Immutable audit trail of all admin operations)
-- (Drops legacy empty table if it existed with old schema referencing admin_users)
DROP TABLE IF EXISTS admin_audit_logs CASCADE;

CREATE TABLE admin_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,                  -- 'grant_plan', 'revoke_plan', 'grant_credits', 'change_role', 'suspend_user', 'unsuspend_user', 'refund_payment'
    target_type TEXT NOT NULL,             -- 'user' | 'payment_transaction' | 'system'
    target_id TEXT,
    details JSONB,                         -- Diff of changes made
    ip_address TEXT,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_admin_audit_admin ON admin_audit_logs(admin_user_id);
CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_audit_action ON admin_audit_logs(action);

-- 4. Create `usage_logs` table (Replaces flat tool_usage_db.json & tracks LLM costs)
CREATE TABLE IF NOT EXISTS usage_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    activity_type TEXT NOT NULL,           -- 'analysis', 'llm_call', 'deep_research', 'llms_txt', 'seo_analyzer', 'auth_login'
    session_id TEXT,
    llm_name TEXT,                         -- 'claude' | 'mistral' | 'google_ai_overview'
    prompt_chars INTEGER DEFAULT 0,
    response_chars INTEGER DEFAULT 0,
    est_cost_usd NUMERIC(10, 6) DEFAULT 0,
    meta JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_usage_user_created ON usage_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_activity ON usage_logs(activity_type, created_at DESC);

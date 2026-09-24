-- ==============================================================================
-- PLANS CMS — MIGRATION A (Steps 1–8)
-- Run this first. It always succeeds regardless of dirty subscription_plan data.
-- After this succeeds, run verification query #5 at the bottom, fix any rows
-- it returns, then run plans_cms_migration_b_fk.sql to add the foreign key.
-- ==============================================================================

BEGIN;

-- ==============================================================================
-- STEP 1: SAFE CANONICALIZATION OF users.subscription_plan
--
-- We ONLY rewrite known aliases. Unknown / custom values are left UNTOUCHED.
-- A NOTICE is raised so you can review them manually.
-- ==============================================================================

DO $$
DECLARE
    unknown_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO unknown_count
    FROM users
    WHERE subscription_plan IS NOT NULL
      AND LOWER(TRIM(subscription_plan)) NOT IN (
          'free',
          'lite plan', 'lite', 'starter',
          'growth plan', 'growth',
          'pro plan', 'pro', 'professional',
          'enterprise', 'custom', 'custom plan'
      );

    IF unknown_count > 0 THEN
        RAISE NOTICE '⚠️  % row(s) in users.subscription_plan have unrecognised values and will NOT be touched. Review them manually before removing the fallback guard.', unknown_count;
    END IF;
END $$;

-- Rewrite known aliases → canonical. Already-canonical values excluded by WHERE.
UPDATE users
SET subscription_plan = CASE
    WHEN LOWER(TRIM(subscription_plan)) IN ('lite plan', 'starter')     THEN 'lite'
    WHEN LOWER(TRIM(subscription_plan)) IN ('growth plan')              THEN 'growth'
    WHEN LOWER(TRIM(subscription_plan)) IN ('pro plan', 'professional') THEN 'pro'
    WHEN LOWER(TRIM(subscription_plan)) IN ('custom', 'custom plan')    THEN 'enterprise'
END
WHERE subscription_plan IS NOT NULL
  AND LOWER(TRIM(subscription_plan)) IN (
      'lite plan', 'starter',
      'growth plan',
      'pro plan', 'professional',
      'custom', 'custom plan'
  );

-- ==============================================================================
-- STEP 2: UPGRADE payment_transactions
--
-- DEFAULT NULL so existing rows clearly signal "pre-snapshot", not ₹0.
-- ==============================================================================
ALTER TABLE payment_transactions
    ADD COLUMN IF NOT EXISTS amount_paise BIGINT DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS currency     TEXT    DEFAULT 'INR';

-- ==============================================================================
-- STEP 3: CREATE plans TABLE
-- ==============================================================================
CREATE TABLE IF NOT EXISTS plans (
    id                               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                             TEXT        NOT NULL UNIQUE,
    display_name                     TEXT        NOT NULL,
    description                      TEXT,
    badge_text                       TEXT,
    monthly_price_paise              BIGINT      NOT NULL DEFAULT 0,
    yearly_price_paise               BIGINT      NOT NULL DEFAULT 0,
    currency                         TEXT        NOT NULL DEFAULT 'INR',
    features                         JSONB       NOT NULL DEFAULT '[]',
    limits                           JSONB       NOT NULL DEFAULT '{"max_projects": 1, "max_prompts_per_project": 5, "max_competitors": 10}',
    is_active                        BOOLEAN     NOT NULL DEFAULT TRUE,
    is_popular                       BOOLEAN     NOT NULL DEFAULT FALSE,
    cta_text                         TEXT        NOT NULL DEFAULT 'Get Started',
    sort_order                       INTEGER     NOT NULL DEFAULT 0,
    version                          INTEGER     NOT NULL DEFAULT 1,
    grandfather_existing_subscribers BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_monthly_price_non_negative CHECK (monthly_price_paise >= 0),
    CONSTRAINT chk_yearly_price_non_negative  CHECK (yearly_price_paise  >= 0),
    CONSTRAINT chk_name_slug                  CHECK (name ~ '^[a-z0-9_-]+$')
);

CREATE INDEX IF NOT EXISTS idx_plans_active_sort ON plans(is_active, sort_order);

-- ==============================================================================
-- STEP 4: CREATE plan_price_history TABLE (immutable audit ledger)
-- ==============================================================================
CREATE TABLE IF NOT EXISTS plan_price_history (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id             UUID        NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    monthly_price_paise BIGINT      NOT NULL,
    yearly_price_paise  BIGINT      NOT NULL,
    currency            TEXT        NOT NULL DEFAULT 'INR',
    changed_by          UUID        REFERENCES users(id) ON DELETE SET NULL,
    change_reason       TEXT,
    effective_from      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plan_price_history_plan
    ON plan_price_history(plan_id, effective_from DESC);

-- ==============================================================================
-- STEP 5: ROW-LEVEL SECURITY
-- ==============================================================================

-- plans: public read for active rows only
ALTER TABLE plans ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow public read on active plans" ON plans;
CREATE POLICY "Allow public read on active plans"
    ON plans FOR SELECT
    USING (is_active = true);

-- plan_price_history: deny direct client reads (service_role bypasses RLS)
ALTER TABLE plan_price_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Deny direct client read on price history" ON plan_price_history;
CREATE POLICY "Deny direct client read on price history"
    ON plan_price_history FOR SELECT
    USING (false);

-- ==============================================================================
-- STEP 6: AUTO-UPDATE updated_at TRIGGER ON plans
-- ==============================================================================
CREATE OR REPLACE FUNCTION set_plans_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_plans_updated_at ON plans;
CREATE TRIGGER trg_plans_updated_at
    BEFORE UPDATE ON plans
    FOR EACH ROW EXECUTE FUNCTION set_plans_updated_at();

-- ==============================================================================
-- STEP 7: PRICE HISTORY TRIGGER
--
-- Fires AFTER UPDATE, records NEW.* prices with effective_from = NOW().
-- Semantics: every row answers "this price became effective at this timestamp."
--
-- Query: "price in effect on date X":
--   SELECT * FROM plan_price_history
--   WHERE plan_id = ? AND effective_from <= X
--   ORDER BY effective_from DESC LIMIT 1;
--
-- The backend CMS endpoint also writes a row explicitly (with changed_by/reason);
-- this trigger catches any direct SQL edits that bypass the API.
-- ==============================================================================
CREATE OR REPLACE FUNCTION record_plan_price_history()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.monthly_price_paise IS DISTINCT FROM OLD.monthly_price_paise)
    OR (NEW.yearly_price_paise  IS DISTINCT FROM OLD.yearly_price_paise) THEN
        INSERT INTO plan_price_history
            (plan_id, monthly_price_paise, yearly_price_paise, currency, change_reason)
        VALUES
            -- NEW.* : the price that just took effect, timestamped NOW()
            (NEW.id, NEW.monthly_price_paise, NEW.yearly_price_paise, NEW.currency,
             'trigger_snapshot_new_price');
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_plan_price_history ON plans;
CREATE TRIGGER trg_plan_price_history
    AFTER UPDATE ON plans   -- AFTER so we read the committed NEW values
    FOR EACH ROW EXECUTE FUNCTION record_plan_price_history();

-- ==============================================================================
-- STEP 8: SEED CANONICAL PLANS
--
-- ON CONFLICT DO NOTHING: if the CMS has already edited a plan, we leave it alone.
-- ==============================================================================
INSERT INTO plans
    (name, display_name, description, badge_text,
     monthly_price_paise, yearly_price_paise, currency,
     features, limits,
     is_active, is_popular, cta_text, sort_order)
VALUES
    ('free', 'Free',
     'Get started with essential AI visibility metrics.',
     NULL, 0, 0, 'INR',
     '["1 Brand Project","Up to 5 Prompts/queries per project","Up to 10 Competitors tracked","AI Engine Rankings (Claude, Mistral, Google AIO)","Basic sentiment & engine presence","Community support"]'::jsonb,
     '{"max_projects": 1, "max_prompts_per_project": 5, "max_competitors": 10}'::jsonb,
     true, false, 'Start Free', 0),

    ('lite', 'Lite',
     'Essential AI search monitoring for emerging brands.',
     NULL, 240000, 2400000, 'INR',
     '["10 Brand Projects","Up to 30 Prompts/queries per project","Up to 10 Competitors tracked","AI Engine Rankings (Claude, Mistral, Google AIO)","AI Recommendations Engine","Standard email support"]'::jsonb,
     '{"max_projects": 10, "max_prompts_per_project": 30, "max_competitors": 10}'::jsonb,
     true, false, 'Upgrade to Lite', 1),

    ('growth', 'Growth',
     'Complete GEO toolset for growing brands & marketing teams.',
     'MOST POPULAR', 650000, 6500000, 'INR',
     '["10 Brand Projects","Up to 30 Prompts/queries per project","Up to 10 Competitors tracked","All AI Engine Rankings + Deeper analysis","AI Recommendations Engine","Full Competitor Analysis & overlap matrix","Priority email & chat support"]'::jsonb,
     '{"max_projects": 10, "max_prompts_per_project": 30, "max_competitors": 10}'::jsonb,
     true, true, 'Upgrade to Growth', 2),

    ('pro', 'Pro',
     'Maximum scale, deep analytics and tailored support for agencies.',
     NULL, 1150000, 11500000, 'INR',
     '["20 Brand Projects","Up to 50 Prompts/queries per project","Up to 10 Competitors tracked","All AI Engines with highest sampling frequency","Advanced Competitor Benchmark & gap analysis","Automated scheduled tracking runs","Dedicated account manager"]'::jsonb,
     '{"max_projects": 20, "max_prompts_per_project": 50, "max_competitors": 10}'::jsonb,
     true, false, 'Upgrade to Pro', 3),

    ('enterprise', 'Enterprise',
     'Custom deployment, dedicated infrastructure, and unlimited scale.',
     NULL, 3700000, 37000000, 'INR',
     '["100 Brand Projects","Up to 100 Prompts/queries per project","Up to 10 Competitors tracked","Custom AI models integration","SLA guarantee (99.9% uptime)","Custom reporting & webhook alerts","24/7 Priority Support"]'::jsonb,
     '{"max_projects": 100, "max_prompts_per_project": 100, "max_competitors": 10}'::jsonb,
     true, false, 'Contact Sales', 4)

ON CONFLICT (name) DO NOTHING;  -- ← NEVER overwrite CMS-managed data

COMMIT;

-- ==============================================================================
-- POST-MIGRATION A VERIFICATION (run these manually after Migration A succeeds)
-- ==============================================================================

-- 1. Canonical spread — should show only: free, lite, growth, pro, enterprise (+ any unknowns)
SELECT subscription_plan, COUNT(*) FROM users GROUP BY subscription_plan ORDER BY COUNT(*) DESC;

-- 2. Plans seeded correctly (prices in paise)
SELECT name, monthly_price_paise, yearly_price_paise FROM plans ORDER BY sort_order;

-- 3. Price history should be empty at this point (no price changes made yet)
SELECT * FROM plan_price_history LIMIT 10;

-- 4. New columns present on payment_transactions
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'payment_transactions'
  AND column_name IN ('amount_paise', 'currency');

-- 5. CRITICAL — rows that need manual review before Migration B can run.
--    Fix any rows returned here (UPDATE them to a canonical plan name),
--    then run plans_cms_migration_b_fk.sql.
--    Expected result: 0 rows.
SELECT id, email, subscription_plan
FROM users
WHERE subscription_plan IS NOT NULL
  AND LOWER(TRIM(subscription_plan)) NOT IN (
      'free',
      'lite plan', 'lite', 'starter',
      'growth plan', 'growth',
      'pro plan', 'pro', 'professional',
      'enterprise', 'custom', 'custom plan'
  );

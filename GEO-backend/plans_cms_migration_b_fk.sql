-- ==============================================================================
-- PLANS CMS — MIGRATION B (Foreign Key)
--
-- Run this ONLY after:
--   1. plans_cms_migration.sql (Migration A) has succeeded.
--   2. Verification query #5 from Migration A returns 0 rows.
--
-- This adds a real FOREIGN KEY so that users.subscription_plan is always a valid
-- entry in plans.name. It auto-extends to any new plan added via the CMS
-- (unlike a hardcoded CHECK list, which would require a re-deploy per new plan).
--
-- IMPORTANT — DELETE BEHAVIOR:
--   The FK is NO ACTION (Postgres default). This means attempting to delete a
--   plan that still has active subscribers will fail with a FK violation.
--   The backend delete_plan() in database_manager.py MUST catch this and return
--   a clear HTTP 400 error: "Cannot delete plan '<name>': N users are subscribed.
--   Reassign or migrate subscribers first." Do NOT surface the raw Postgres error.
-- ==============================================================================

BEGIN;

-- Pre-flight: abort the whole transaction if any dirty rows still exist.
-- This ensures the constraint is never added against inconsistent data.
DO $$
DECLARE
    bad_count INTEGER;
    bad_sample TEXT;
BEGIN
    SELECT COUNT(*), STRING_AGG(subscription_plan, ', ' ORDER BY subscription_plan)
    INTO bad_count, bad_sample
    FROM (
        SELECT DISTINCT subscription_plan
        FROM users
        WHERE subscription_plan IS NOT NULL
          AND subscription_plan NOT IN (SELECT name FROM plans)
        LIMIT 5
    ) t;

    IF bad_count > 0 THEN
        RAISE EXCEPTION
            E'❌ Migration B blocked: % user row(s) have subscription_plan values not in plans.name.\nSample unrecognised values: %\nFix them manually (see verification query #5 in plans_cms_migration.sql), then re-run this file.',
            bad_count, bad_sample;
    END IF;
END $$;

-- Drop the old hardcoded CHECK constraint if it was ever added, then add the
-- real FK that automatically covers any future plan created via the CMS.
ALTER TABLE users
    DROP CONSTRAINT IF EXISTS chk_users_subscription_plan_valid;

ALTER TABLE users
    DROP CONSTRAINT IF EXISTS fk_users_subscription_plan;

ALTER TABLE users
    ADD CONSTRAINT fk_users_subscription_plan
    FOREIGN KEY (subscription_plan)
    REFERENCES plans(name)
    ON UPDATE CASCADE   -- if a plan name is ever renamed, cascade to users
    ON DELETE RESTRICT; -- block plan deletion while subscribers exist (handled in app)

COMMIT;

-- ==============================================================================
-- VERIFICATION
-- ==============================================================================

-- Confirm the FK exists
SELECT conname, contype, confupdtype, confdeltype
FROM pg_constraint
WHERE conname = 'fk_users_subscription_plan';
-- Expected: contype = 'f', confupdtype = 'c' (CASCADE), confdeltype = 'r' (RESTRICT)

-- ==============================================================================
-- GEO PLATFORM - SECURITY FIX: ENABLE ROW LEVEL SECURITY (RLS) ON ALL TABLES
-- ==============================================================================
-- Resolves Supabase Security Advisor alert: 'rls_disabled_in_public'
--
-- WHY THIS HAPPENED:
-- Supabase automatically exposes an HTTP PostgREST API for all tables in the
-- 'public' schema. If RLS is disabled, anyone with your Supabase URL and public
-- anon key can directly query or modify your database tables.
--
-- WHY THIS FIX IS SAFE FOR YOUR APP:
-- Your frontend communicates ONLY with your FastAPI backend.
-- Your FastAPI backend connects to Supabase using the service_role key (SUPABASE_KEY).
-- The service_role key automatically BYPASSES RLS in PostgreSQL.
-- Therefore, enabling RLS closes the public internet loophole completely while
-- having ZERO impact on your backend or frontend application.
-- ==============================================================================

BEGIN;

-- 1. Enable RLS on every public table dynamically
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT tablename 
        FROM pg_tables 
        WHERE schemaname = 'public'
          AND tablename NOT LIKE 'pg_%'
    ) LOOP
        EXECUTE 'ALTER TABLE public.' || quote_ident(r.tablename) || ' ENABLE ROW LEVEL SECURITY;';
        RAISE NOTICE 'Enabled RLS on public.%', r.tablename;
    END LOOP;
END $$;

COMMIT;

-- ------------------------------------------------------------------------------
-- VERIFICATION QUERY
-- ------------------------------------------------------------------------------
-- Expected result: 0 rows returned (confirming no public tables have RLS disabled).
SELECT 
    schemaname,
    tablename,
    rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
  AND rowsecurity = false;

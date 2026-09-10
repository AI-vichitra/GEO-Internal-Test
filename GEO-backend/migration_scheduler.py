"""
Migration via Supabase REST (uses service-role key if available, else anon key).
Runs the scheduler DDL statements one at a time using the /rest/v1/rpc approach,
OR uses the supabase-py client's postgrest execute_raw if available.
"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# Try service role key (bypasses RLS) if set
SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", SUPABASE_KEY)

supabase = create_client(SUPABASE_URL, SERVICE_ROLE_KEY)

STATEMENTS = [
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS sync_status TEXT NOT NULL DEFAULT 'idle'",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS sync_started_at TIMESTAMPTZ",
    "ALTER TABLE projects ADD COLUMN IF NOT EXISTS last_sync_at TIMESTAMPTZ",
    "ALTER TABLE projects ALTER COLUMN is_active SET DEFAULT FALSE",
    """CREATE INDEX IF NOT EXISTS idx_projects_scheduler ON projects (is_active, sync_status, last_sync_at)""",
    """
    CREATE TABLE IF NOT EXISTS daily_brand_metrics (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        llm_name TEXT NOT NULL,
        date DATE NOT NULL DEFAULT CURRENT_DATE,
        visibility_score REAL NOT NULL DEFAULT 0,
        avg_position REAL,
        mention_count INTEGER NOT NULL DEFAULT 0,
        total_prompts INTEGER NOT NULL DEFAULT 0,
        session_ids TEXT[] NOT NULL DEFAULT '{}',
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        UNIQUE(project_id, llm_name, date)
    )
    """,
    """CREATE INDEX IF NOT EXISTS idx_daily_brand_metrics_proj_date ON daily_brand_metrics (project_id, date)""",
]

def run():
    for i, stmt in enumerate(STATEMENTS, 1):
        try:
            # supabase-py v2 uses .rpc() for arbitrary SQL or we do direct table ops
            # For DDL we use the postgres connection via rpc if there's a helper function
            # Fallback: try direct postgrest (won't work for DDL)
            # Best approach: use the database directly through the SQL editor
            print(f"Statement {i}: {stmt.strip()[:60]}...")
            # We'll use supabase postgrest raw query via rpc if available
            # For DDL the safest approach is to use the Supabase SQL editor or direct DB connection
            # Let's attempt via the client's raw query capability
            result = supabase.rpc("exec_sql", {"query": stmt}).execute()
            print(f"  ✅ OK: {result}")
        except Exception as e:
            print(f"  ⚠️  Error (may be expected if already exists): {e}")

if __name__ == "__main__":
    run()
    print("\n--- Alternative: Run these in Supabase SQL Editor ---")
    for stmt in STATEMENTS:
        print(stmt.strip() + ";")
        print()

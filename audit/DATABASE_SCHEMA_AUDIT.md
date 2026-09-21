# GEO Database Schema — Design Audit

**Date:** 2026-09-16
**Scope:** Full review of `schema_staging.sql` cross-referenced against actual column/table usage in `database_manager.py`, `app.py`, all services, and migration scripts.
**Target:** Supabase PostgreSQL.

---

## Summary

| Category | Severity | Finding |
|---|---|---|
| Multiple schema definitions | High | Schema exists in 3 places that have diverged |
| Dead columns | Medium | 7 columns never written/read; increase storage and confusion |
| Duplicate/denormalized data | Medium | `razorpay_payment_id` written in 2 tables, email duplicated |
| Missing NOT NULL constraints | Medium | `users.password_hash` allows NULL (Google auth), `user_id` nullable in sessions |
| TEXT timestamps | High | `analysis_sessions.timestamp` is TEXT not TIMESTAMPTZ; breaks queries and ordering |
| Missing composite indexes | Medium | Biggest tables lack multi-column indexes for common query paths |
| Unused table: `saved_prompts` | Medium | Global (no `user_id`), cross-tenant overwrite, superseded by cohort flow |
| Serial vs UUID inconsistency | Low | 6 tables use SERIAL, 5 use UUID — no clear pattern |
| `llm_responses.project_id` redundant FK | Low | Redundant with `session_id` → `analysis_sessions.project_id`; never queried |
| Cross-tenant schema leak | High | `saved_prompts` UNIQUE constraint is global, not per-user |
| No RLS policies | Critical | (Already flagged in code review; restated here for schema completeness) |

---

## 1. Three Divergent Schema Definitions (DRY Violation)

The schema is defined in **three separate places**, all of which have drifted:

| Source | What it defines | Actually executed? |
|---|---|---|
| `schema_staging.sql` | All 14 tables, indexes, `users`, `payment_transactions` | Yes — applied manually in SQL Editor |
| `database_manager.py:83-230` (`init_database()`) | 11 tables (omits `users`, `payment_transactions`, `saved_prompts`) | No — only **logs** SQL at startup; never executes |
| `migration_scheduler.py` | Adds `projects` scheduler columns + redefines `daily_brand_metrics` with `session_ids TEXT[]`, `updated_at` | No — references non-existent `exec_sql` RPC; stale |

**Concrete divergence in `daily_brand_metrics`:**

| Column | `schema_staging.sql` | `migration_scheduler.py` | Actually written by `record_daily_metrics()` |
|---|---|---|---|
| `citation_count` | ✅ present | ❌ missing | ❌ never written |
| `session_ids` | ❌ missing | ✅ present (`TEXT[]`) | ❌ never written |
| `updated_at` | ❌ missing | ✅ present (`TIMESTAMPTZ`) | ❌ never written |

**Fix:** Delete the `init_database()` SQL string and `migration_scheduler.py` entirely. Treat `schema_staging.sql` as the single source of truth. For ongoing DDL changes, use a numbered migration file approach (e.g., `migrations/001_add_admin_roles.sql`) rather than ad-hoc scripts.

---

## 2. Dead Columns (never written or read in production)

These columns exist in the schema but are never populated or queried in any production code path:

| Table | Column | Status | Root cause |
|---|---|---|---|
| `users` | `is_verified` | NEVER set to TRUE | Signup returns JWT immediately; no email verification flow exists |
| `users` | `verification_otp` | NEVER populated | No verification email sent; no OTP validation endpoint |
| `users` | `razorpay_payment_id` | WRITTEN, NEVER READ | Duplicates `payment_transactions.razorpay_payment_id`; only last payment retained |
| `projects` | `logo_url` | NEVER written/read | No upload or display logic in backend |
| `projects` | `country` | NEVER read in queries | Only appears in local `brightdata_scraper.py` variables (not stored) |
| `projects` | `city` | NEVER written/read | Only appears in SEO prompt template strings |
| `daily_brand_metrics` | `citation_count` | NEVER written | `record_daily_metrics()` omits it from upsert payload |

**Fix:** Remove all 7 columns. If email verification or logo upload is planned, add them when implementing the feature. `users.razorpay_payment_id` is directly redundant with `payment_transactions` and should be dropped.

---

## 3. Duplicate / Denormalized Data

### 3a. `users.razorpay_payment_id` ↔ `payment_transactions.razorpay_payment_id`

The users table stores only the *most recent* payment ID. The `payment_transactions` table is the immutable audit ledger and already holds it with full context. The users column is never read by any query — it's pure write-only duplication.

**Fix:** Remove `users.razorpay_payment_id`. Read it from `payment_transactions` when needed (or don't — the last payment ID has no practical use).

### 3b. `payment_transactions.user_email` (denormalized copy of `users.email`)

Written at payment verification time. Defensible as a historical snapshot if emails are ever editable, but currently no email change feature exists. Mild duplication.

**Fix (future):** If email-edit is ever added, keep this column as historical audit. For now, it's low-risk but unnecessary.

### 3c. `project_id` in `llm_responses` and `scoring_results`

Both tables have a `project_id UUID REFERENCES projects(id)` foreign key *in addition to* the `session_id` FK. Since `analysis_sessions` already has `project_id`, these columns are redundant denormalization.

They are **never used in queries** — only set to `ON DELETE SET NULL`. Adding them increases storage and write overhead for zero read benefit.

**Fix:** Drop `project_id` from `llm_responses` and `scoring_results`. Derive project from the session if needed.

### 3d. Timestamps stored redundantly across 4 tables

`timestamp TEXT` is stored in `analysis_sessions`, `cohorts`, `prompts_cohort_mapping`, `scoring_results`, and `share_of_voice` — all referencing the same session. Each stores its own copy, leading to inconsistencies if writes are partial.

**Fix:** Remove `timestamp` from child tables (`cohorts`, `prompts_cohort_mapping`, `scoring_results`, `share_of_voice`). Resolve from `analysis_sessions.timestamp` via the `session_id` FK.

---

## 4. Data Type Issues

### 4a. `analysis_sessions.timestamp` is TEXT, not TIMESTAMPTZ

This is the most significant data type issue in the schema. The column stores ISO 8601 strings (`datetime.now().isoformat()`), so string ordering *works* by coincidence, but SQL date operations fail:

- Cannot use `WHERE timestamp > '2026-09-01'::timestamptz` (type mismatch)
- Cannot use `ORDER BY timestamp` efficiently (text collation vs timestamp ordering)
- Cannot use date range functions (`date_trunc`, `AGE()`, interval arithmetic)
- History endpoints do manual string splitting: `timestamp.split('T')[0]`

**Fix:** Migrate to `TIMESTAMPTZ`:
```sql
ALTER TABLE analysis_sessions
  ALTER COLUMN timestamp TYPE TIMESTAMPTZ USING timestamp::timestamptz;
```
Do the same for `cohorts.timestamp`, `scoring_results.timestamp`, `share_of_voice.timestamp`. Replace `datetime.now().isoformat()` with `datetime.now(timezone.utc).isoformat()` in `save_session()`.

### 4b. `SERIAL` vs `UUID` primary key inconsistency

| UUID PKs | SERIAL PKs |
|---|---|
| `users`, `projects`, `monitored_prompts`, `monitored_competitors`, `daily_brand_metrics` | `cohorts`, `prompts_cohort_mapping`, `llm_responses`, `scoring_results`, `competitors`, `share_of_voice`, `saved_prompts` |

There's no clear architectural reason for the split. SERIAL PKs work fine at this scale but make cross-service ID comparison inconsistent and cannot be generated client-side.

**Fix:** Standardize on UUID for all tables going forward. For existing SERIAL tables, don't change (the effort/risk outweighs the benefit); just use UUID for new tables (e.g., the planned `admin_audit_logs`, `usage_logs`).

---

## 5. Missing Indexes

These are identified by matching actual query patterns in `database_manager.py` and `app.py` against the existing index set:

| Query pattern | Current index used | Missing index |
|---|---|---|
| `llm_responses WHERE session_id = ? AND llm_name = ?` (scoring) | `idx_llm_responses_session` (single-col) | `idx_llm_responses_session_llm(session_id, llm_name)` |
| `scoring_results WHERE session_id = ? AND llm_name != 'SUMMARY'` | `idx_scoring_results_session` (single-col) | `idx_scoring_results_session_llm(session_id, llm_name)` |
| `share_of_voice WHERE session_id = ? AND brand_name = ?` | `idx_share_of_voice_session` | `idx_share_of_voice_session_brand(session_id, brand_name)` |
| `analysis_sessions WHERE project_id = ? AND user_id = ?` (project page) | `idx_analysis_sessions_project` | `idx_analysis_sessions_project_user(project_id, user_id)` |
| `payment_transactions WHERE user_id = ? ORDER BY created_at DESC` | `idx_payment_transactions_user` | `idx_payment_transactions_user_date(user_id, created_at DESC)` |
| `llm_responses` total count per session | `idx_llm_responses_session` | Already sufficient (single-col covers `COUNT(*) WHERE session_id = ?`) |

**Fix:**
```sql
CREATE INDEX IF NOT EXISTS idx_llm_responses_session_llm ON llm_responses(session_id, llm_name);
CREATE INDEX IF NOT EXISTS idx_scoring_results_session_llm ON scoring_results(session_id, llm_name);
CREATE INDEX IF NOT EXISTS idx_share_of_voice_session_brand ON share_of_voice(session_id, brand_name);
CREATE INDEX IF NOT EXISTS idx_analysis_sessions_project_user ON analysis_sessions(project_id, user_id);
CREATE INDEX IF NOT EXISTS idx_payment_transactions_user_date ON payment_transactions(user_id, created_at DESC);
```

---

## 6. Constraint / NULLability Issues

### 6a. `users.password_hash` is nullable

`password_hash TEXT` allows NULL, which is intentional for Google OAuth users (who don't set a password). However, the login endpoint does `verify_password(request.password, user['password_hash'])` — if a Google-only user tries password login, this crashes on `None`.

**Fix:** Add an explicit check before password verification:
```python
if not user.get('password_hash'):
    raise HTTPException(status_code=400, detail="This account uses Google Sign-In")
```

### 6b. `analysis_sessions.user_id` allows NULL (in schema_staging.sql)

Line 124: `user_id UUID REFERENCES users(id) ON DELETE CASCADE` — no `NOT NULL`. The `init_database()` string (line 132) says `NOT NULL`, creating a schema mismatch. If a session is created without a user (e.g., legacy import), the IDOR check `verify_session_owner` will allow any user to access it (since `stored_user_id` is None, the check passes).

**Fix:** Add `NOT NULL` to `user_id` in the canonical schema and backfill any existing NULL rows.

### 6c. `analysis_sessions` upsert on `session_id` PK

`save_session()` uses `upsert(data).execute()` (line 275). If a session ID happens to collide (unlikely with the random hex suffix, but possible), existing session data is silently overwritten without warning. This is a data integrity risk.

**Fix:** Use `insert(...).execute()` and handle the duplicate-key error explicitly, or at minimum log when an upsert overwrites an existing row.

---

## 7. Cross-Tenant Schema Bug: `saved_prompts`

```sql
CREATE TABLE saved_prompts (
    id SERIAL PRIMARY KEY,
    brand_name TEXT NOT NULL,
    product_name TEXT,
    prompts_json JSONB NOT NULL,
    timestamp TEXT NOT NULL,
    UNIQUE(brand_name, product_name)  -- Global unique — no user_id
);
```

**Problem:** The UNIQUE constraint is on `(brand_name, product_name)` with **no `user_id` column**. This means:
- User A saves prompts for "Nike shoes" → row created
- User B saves prompts for "Nike shoes" → **upserts over User A's row** (silent overwrite)
- Every user sees the same saved prompts for any brand+product combination

**Fix options:**
1. **Remove the table entirely** — the cohort-based prompt system (`prompts_cohort_mapping`) is already the production prompt store. `saved_prompts` is vestigial.
2. If retained: add `user_id UUID REFERENCES users(id)`, change UNIQUE to `UNIQUE(user_id, brand_name, product_name)`.

---

## 8. Unused / Vestigial Code

| File | Issue |
|---|---|
| `database_manager.py:75-233` (`init_database()`) | Logs a schema string but never executes it; called at startup. Dead code, creates confusion about actual schema. |
| `migration_scheduler.py` | Standalone script referencing non-existent `exec_sql` RPC; defines divergent `daily_brand_metrics`. Stale. |
| `migration_add_aliases.py` | One-shot migration for `brand_aliases` column; references SQLite `brand_visibility.db` (doesn't exist anymore). Dead. |
| `verify_citation_repo.py` | Debug script using `get_all_sessions()` (no user filter) against a non-existent `prompts` table (line 56: `.table('prompts')`). Dead. |
| `debug_session.py` | References `.table('prompts')` (non-existent table). Dead. |

**Fix:** Delete all five. Run `git rm` to remove them from the repo. The `brand_aliases` column is already in the live DB; the migration script has served its purpose.

---

## 9. Recommended Schema Changes (Priority Order)

| Priority | Change | SQL |
|---|---|---|
| 🔴 Critical | Enable RLS on all tables | `ALTER TABLE users ENABLE ROW LEVEL SECURITY;` ... (already flagged in code review) |
| 🔴 Critical | Add `user_id NOT NULL` + backfill NULL sessions | `UPDATE analysis_sessions SET user_id = 'system' WHERE user_id IS NULL; ALTER TABLE ...` |
| 🔴 Critical | Add `NOT NULL` check to `verify_session_owner` for null user_id | Code fix in `app.py` |
| 🟠 High | Add `password_hash` null check before password verify | Code fix in `app.py` login flow |
| 🟠 High | Add composite indexes (§5) | 5 new indexes (SQL above) |
| 🟠 High | Migrate `timestamp TEXT` → `TIMESTAMPTZ` | ALTER TYPE on 5 tables |
| 🟡 Medium | Drop dead columns (§2): `users.is_verified`, `verification_otp`, `razorpay_payment_id`; `projects.logo_url`, `country`, `city`; `daily_brand_metrics.citation_count` | `ALTER TABLE ... DROP COLUMN IF EXISTS` |
| 🟡 Medium | Drop `project_id` from `llm_responses` + `scoring_results` | `ALTER TABLE ... DROP COLUMN IF EXISTS` |
| 🟡 Medium | Remove `timestamp` from child tables (§3d) | 4 `ALTER TABLE` statements |
| 🟡 Medium | Delete vestigial files (§8) | `git rm` 5 files |
| 🟡 Medium | Consolidate schema to single source of truth | Delete `init_database()` SQL string; delete `migration_scheduler.py` |
| 🟢 Low | Standardize new tables to UUID PKs | Apply to new tables only |

---

## 10. Scalability Considerations

| Concern | Current state | Recommendation |
|---|---|---|
| **RLS disabled** | All queries run with service-role key; no row-level isolation in DB | Implement RLS per table (user_id-based policies); keeps app layer honest |
| **No table partitioning** | `llm_responses` grows unbounded (50+ prompts × 2 LLMs × sessions) | After ~100k rows, consider partitioning `llm_responses` by `session_id` range or date |
| **SERIAL PKs on high-volume tables** | `llm_responses.id SERIAL` can overflow in extreme cases (unlikely) | Switch to BIGSERIAL if expecting >2B rows; or migrate to UUID |
| **No connection pooling** | `supabase-py` creates HTTP connections; Supabase manages PG pool | Fine for staging; for production consider PgBouncer (Supabase Pro includes this) |
| **JSONB columns (`research_data`, `keywords`, `citations`)** | Stores variable-length lists | Index with GIN if queryable; currently these are only fetched in full, not searched |
| **TEXT timestamps** | Cannot do range queries efficiently | Migrate to TIMESTAMPTZ to enable proper indexing and SQL range filters |

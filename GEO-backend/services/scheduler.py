"""
scheduler.py – Scheduled analysis worker for GEO projects.

Called by:
  1. POST /api/cron/process-scheduled-projects  (external cron trigger)
  2. start_scheduler_loop()  (optional in-process background loop for single-instance setups)

Flow per project:
  claim → fetch prompts (with session fallback) → fetch competitors → create session → run LLMs → score → aggregate → release
"""
import asyncio
import logging
from typing import List

logger = logging.getLogger(__name__)


def _get_prompts_and_llms_for_project(project_id: str) -> tuple[List[str], List[str]]:
    """
    Returns (prompts, llms) to use for scheduled analysis.

    Prompts Priority:
      1. Rows in `monitored_prompts` for the project.
      2. Fallback: prompts from the most recent completed analysis session
         (via `llm_responses` which contains ONLY the user-selected analyzed prompts).
         These are back-filled into `monitored_prompts`.

    LLMs:
      - Inherits the exact set of LLMs analyzed in the previous completed session
        (via `llm_responses.llm_name`).
      - Defaults to ["ChatGPT", "Gemini"] only if no previous session or LLMs exist.
    """
    from services.database_manager import supabase, get_monitored_prompts, add_monitored_prompts

    # 1. Fetch prompts from monitored_prompts
    rows = get_monitored_prompts(project_id)
    prompts = [r["prompt_text"] for r in (rows or []) if r.get("prompt_text")]

    # 2. Check latest completed session for fallback prompts & selected LLMs
    selected_llms = ["ChatGPT", "Gemini"]
    try:
        session_res = (
            supabase.table("analysis_sessions")
            .select("session_id")
            .eq("project_id", project_id)
            .eq("status", "completed")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        if session_res.data:
            latest_session_id = session_res.data[0]["session_id"]

            # Query llm_responses from previous session
            resp_res = (
                supabase.table("llm_responses")
                .select("prompt_text, llm_name")
                .eq("session_id", latest_session_id)
                .execute()
            )
            raw_responses = resp_res.data or []

            # Extract distinct LLMs used in that session
            session_llms = list(dict.fromkeys(
                r["llm_name"] for r in raw_responses if r.get("llm_name")
            ))
            if session_llms:
                selected_llms = session_llms
                logger.info(
                    f"Scheduler: Inherited LLMs from previous session {latest_session_id}: {selected_llms}"
                )

            # If monitored_prompts was empty, fallback to the exact prompts analyzed in that session
            if not prompts:
                session_prompts = list(dict.fromkeys(
                    r["prompt_text"] for r in raw_responses if r.get("prompt_text")
                ))
                if session_prompts:
                    prompts = session_prompts
                    add_monitored_prompts(project_id, prompts)
                    logger.info(
                        f"Scheduler: back-filled {len(prompts)} analyzed prompts into "
                        f"monitored_prompts for project {project_id}"
                    )
    except Exception as e:
        logger.warning(f"Scheduler: error fetching previous session context for {project_id}: {e}")

    return prompts, selected_llms


async def process_due_projects() -> dict:
    """
    Main scheduler entry point.
    Claims all due projects and runs their analysis in sequence.
    Returns a summary dict.
    """
    from services.database_manager import (
        claim_due_projects,
        release_project_lock,
        get_monitored_prompts,
        get_monitored_competitors,
        add_monitored_prompts,
        save_session,
        create_session_id,
        update_session_status,
        get_subscription_status,
        record_daily_metrics,
    )

    claimed = claim_due_projects(limit=10)
    if not claimed:
        logger.info("Scheduler: No projects due for sync")
        return {"projects_processed": 0}

    results = []
    for project in claimed:
        project_id = project["id"]
        project_name = project.get("name", project_id)
        user_id = project.get("user_id")

        logger.info(f"Scheduler: Processing project '{project_name}' ({project_id})")
        success = False

        try:
            # 1. Check user plan (graceful skip on error)
            try:
                sub = get_subscription_status(user_id) or {}
                plan = (sub.get("subscription_plan") or "free").lower()
            except Exception:
                plan = "free"

            # 2. Fetch prompts & LLMs from project/previous session
            selected_prompts, selected_llms = _get_prompts_and_llms_for_project(project_id)
            if not selected_prompts:
                logger.warning(
                    f"Scheduler: Project '{project_name}' ({project_id}) has no "
                    f"prompts in monitored_prompts or any completed session – skipping. "
                    f"Stamping last_sync_at to prevent queue starvation."
                )
                # Stamp last_sync_at so this project doesn't block the queue on
                # every tick while it has no prompts configured.
                release_project_lock(project_id, success=True)
                results.append(
                    {"project_id": project_id, "status": "skipped", "reason": "no_prompts"}
                )
                continue

            logger.info(
                f"Scheduler: Project '{project_name}' running with {len(selected_prompts)} prompts "
                f"on LLMs: {selected_llms}"
            )

            # 3. Fetch monitored competitors
            # `monitored_competitors` column is `name` (not `competitor_name`)
            competitors_rows = get_monitored_competitors(project_id)
            selected_competitors = [
                r["name"] for r in (competitors_rows or []) if r.get("name")
            ]

            # 5. Create a new session linked to this project
            # save_session signature: (session_id, brand_name, user_id, product_name,
            #                          website_url, research_data, keywords, industry,
            #                          project_id, brand_aliases)
            session_id = create_session_id(project_name)
            save_session(
                session_id,
                project_name,
                user_id,
                None,                           # product_name
                project.get("website_url"),     # website_url
                {"is_scheduled": True},         # research_data: mark as automated run
                [],                             # keywords
                project.get("industry"),        # industry
                project_id,                     # project_id
                [],                             # brand_aliases
            )
            update_session_status(
                session_id, status="running", progress=10, step="Scheduled run started"
            )

            # 6. Run LLM + scoring workflow
            # Competitors are passed via save_competitors inside execute_prompts_workflow
            # if it detects them in session; here we patch the session competitors table
            # before executing so the scoring picks them up.
            if selected_competitors:
                from services.database_manager import save_competitors
                save_competitors(session_id, selected_competitors)

            from app import execute_prompts_workflow  # noqa: PLC0415
            await execute_prompts_workflow(session_id, selected_prompts, selected_llms)

            # 7. Record daily metrics (idempotent upsert)
            agg_result = record_daily_metrics(session_id)
            logger.info(f"Scheduler: daily_metrics result for '{project_name}': {agg_result}")

            success = True
            results.append(
                {"project_id": project_id, "session_id": session_id, "status": "completed"}
            )

        except Exception as e:
            logger.error(
                f"Scheduler: Error processing project '{project_name}' ({project_id}): {e}",
                exc_info=True,
            )
            results.append({"project_id": project_id, "status": "error", "error": str(e)})

        finally:
            release_project_lock(project_id, success=success)

    return {"projects_processed": len(claimed), "results": results}


def start_scheduler_loop(interval_seconds: int = 3600):
    """
    Optional: starts an asyncio background task that triggers process_due_projects()
    every `interval_seconds`. Use when ENABLE_SCHEDULER=true in .env and running
    on a single server instance (Railway, Fly.io, etc.).
    """
    async def _loop():
        logger.info(f"Scheduler loop started (interval={interval_seconds}s)")
        while True:
            try:
                await process_due_projects()
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}", exc_info=True)
            await asyncio.sleep(interval_seconds)

    loop = asyncio.get_event_loop()
    loop.create_task(_loop())
    logger.info("Scheduler background task registered")

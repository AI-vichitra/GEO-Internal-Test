"""
scheduler.py – Scheduled analysis worker for GEO projects.

Called by:
  1. POST /api/cron/process-scheduled-projects  (external cron trigger)
  2. start_scheduler_loop()  (optional in-process background loop for single-instance setups)

Flow per project:
  claim → fetch prompts/competitors → create session → run LLMs → score → aggregate → release
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


async def process_due_projects() -> dict:
    """
    Main scheduler entry point.
    Claims all due projects and runs their analysis in sequence.
    Returns a summary dict.
    """
    from services.database_manager import (
        claim_due_projects, release_project_lock,
        get_monitored_prompts, get_monitored_competitors,
        save_session, create_session_id, update_session_status,
        get_subscription_status, record_daily_metrics,
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
            # 1. Check user plan limits (graceful skip on error)
            try:
                sub = get_subscription_status(user_id) or {}
                plan = (sub.get("subscription_plan") or "free").lower()
            except Exception:
                plan = "free"

            # 2. Fetch active monitored prompts
            prompts_rows = get_monitored_prompts(project_id)
            selected_prompts = [r["prompt_text"] for r in (prompts_rows or []) if r.get("prompt_text")]
            if not selected_prompts:
                logger.warning(f"Scheduler: Project {project_id} has no monitored prompts – skipping")
                release_project_lock(project_id, success=False)
                results.append({"project_id": project_id, "status": "skipped", "reason": "no_prompts"})
                continue

            # 3. Fetch active monitored competitors
            competitors_rows = get_monitored_competitors(project_id)
            selected_competitors = [r["competitor_name"] for r in (competitors_rows or []) if r.get("competitor_name")]

            # 4. Determine LLMs from project config or default
            selected_llms = project.get("selected_llms") or ["ChatGPT", "Gemini"]

            # 5. Create a new session linked to this project
            session_id = create_session_id()
            session_saved = save_session(
                session_id=session_id,
                brand_name=project_name,
                product_name=project.get("website_url", ""),
                industry=project.get("industry", ""),
                website_url=project.get("website_url", ""),
                selected_llms=selected_llms,
                num_prompts=len(selected_prompts),
                research_data={},
                keywords=[],
                brand_aliases=[],
                user_id=user_id,
                project_id=project_id,
            )
            if not session_saved:
                raise RuntimeError("Failed to save scheduled session")

            update_session_status(session_id, status="running", progress=10, step="Scheduled run started")

            # 6. Run the full LLM + scoring workflow (reuse existing function)
            # Import here to avoid circular imports at module load time
            from app import execute_prompts_workflow  # noqa: PLC0415
            await execute_prompts_workflow(session_id, selected_prompts, selected_llms)

            # 7. Record daily metrics (idempotent)
            agg_result = record_daily_metrics(session_id)
            logger.info(f"Scheduler: daily_metrics result: {agg_result}")

            success = True
            results.append({"project_id": project_id, "session_id": session_id, "status": "completed"})

        except Exception as e:
            logger.error(f"Scheduler: Error processing project {project_id}: {e}", exc_info=True)
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

import os
import json
import traceback
import httpx
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import logging
from urllib.parse import urlparse
from collections import Counter
from supabase import create_client, Client
from supabase.client import ClientOptions
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Initialize Supabase client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY (or SUPABASE_SERVICE_ROLE_KEY) must be set in environment variables")

if SUPABASE_KEY.startswith("sb_publish_") or "anon" in SUPABASE_KEY[:20].lower():
    logger.warning("⚠️ SUPABASE_KEY appears to be a publishable/anon key. If Row Level Security (RLS) is enabled, backend operations will be subject to RLS restrictions. Use the service_role key for full backend access.")


# ✅ FIX: Disable HTTP/2 to resolve [WinError 10035] WSAEWOULDBLOCK on Windows + Python 3.14
# The default Supabase client uses httpx with HTTP/2 which has non-blocking socket issues on Windows.
_httpx_client = httpx.Client(http2=False, timeout=30.0)
supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY,
    options=ClientOptions(httpx_client=_httpx_client)
)

# --- STATUS MANAGEMENT (The Fix for Global Variable Issue) ---

def update_session_status(session_id: str, status: str = None, progress: int = None, step: str = None, error: str = None):
    """
    Updates the progress/status of a session in the DB.
    Replaces the global dictionary in app.py.
    """
    try:
        update_data = {}
        if status: update_data['status'] = status
        if progress is not None: update_data['progress'] = progress
        if step: update_data['current_step'] = step
        if error: update_data['error_message'] = error
        
        if update_data:
            # Check if session exists first to avoid errors
            supabase.table('analysis_sessions').update(update_data).eq('session_id', session_id).execute()
    except Exception as e:
        logger.error(f"Failed to update session status: {e}")

def get_session_status(session_id: str) -> Dict[str, Any]:
    """Retrieves status from DB."""
    try:
        response = supabase.table('analysis_sessions').select('status, progress, current_step, error_message').eq('session_id', session_id).execute()
        if response.data:
            return response.data[0]
        return {"status": "not_found", "progress": 0}
    except Exception as e:
        logger.error(f"Failed to get session status: {e}")
        return {"status": "error", "progress": 0}

def get_session_metadata(session_id: str) -> Optional[Dict[str, Any]]:
    """Helper to get just the session metadata for copying/forking."""
    try:
        response = supabase.table('analysis_sessions').select('*').eq('session_id', session_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error fetching session metadata: {e}")
        return None

def init_database():
    """
    Initialize Supabase database with schema
    Note: Tables should be created via Supabase SQL Editor using the schema below
    """
    logger.info("Using Supabase database")
    logger.info("Ensure tables are created in Supabase SQL Editor with the following schema:")
    
    schema_sql = """ 
    CREATE TABLE IF NOT EXISTS projects (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        website_url TEXT,
        industry TEXT,
        update_frequency TEXT DEFAULT '24h',
        is_active BOOLEAN DEFAULT TRUE,
        last_sync_at TIMESTAMP WITH TIME ZONE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- Monitored Prompts for a project
    CREATE TABLE IF NOT EXISTS monitored_prompts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        prompt_text TEXT NOT NULL,
        is_active BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- Monitored Competitors for a project
    CREATE TABLE IF NOT EXISTS monitored_competitors (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- Daily Metrics for historical tracking (Real-time Dashboard Source)
    CREATE TABLE IF NOT EXISTS daily_brand_metrics (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        llm_name TEXT NOT NULL,
        visibility_score REAL,
        avg_position REAL,
        mention_count INTEGER,
        total_prompts INTEGER,
        citation_count INTEGER,
        date DATE NOT NULL DEFAULT CURRENT_DATE,
        UNIQUE(project_id, llm_name, date)
    );

    -- Main analysis sessions table (Updated to link to project)
    CREATE TABLE IF NOT EXISTS analysis_sessions (
        session_id TEXT PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        project_id UUID REFERENCES projects(id) ON DELETE SET NULL, -- Link to project
        brand_name TEXT NOT NULL,
        product_name TEXT,
        industry TEXT,
        website_url TEXT,
        timestamp TEXT NOT NULL,
        research_data JSONB,
        keywords JSONB,
        status TEXT DEFAULT 'pending',
        current_step TEXT,
        progress INTEGER DEFAULT 0,
        error_message TEXT
    );
    
    -- LLM responses table (Updated to link to project)
    CREATE TABLE IF NOT EXISTS llm_responses (
        id SERIAL PRIMARY KEY,
        prompt_id TEXT NOT NULL,
        session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id),
        project_id UUID REFERENCES projects(id) ON DELETE SET NULL, -- Link to project
        llm_name TEXT NOT NULL,
        prompt_text TEXT NOT NULL,
        response_text TEXT NOT NULL,
        citations JSONB,
        timestamp TEXT NOT NULL
    );
    
    -- Scoring results table (Updated to link to project)
    CREATE TABLE IF NOT EXISTS scoring_results (
        id SERIAL PRIMARY KEY,
        prompt_id TEXT NOT NULL,
        session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id),
        project_id UUID REFERENCES projects(id) ON DELETE SET NULL, -- Link to project
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
    
    -- Competitors table
    CREATE TABLE IF NOT EXISTS competitors (
        id SERIAL PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id),
        competitor_name TEXT NOT NULL,
        rank INTEGER
    );
    
    -- Share of Voice results table
    CREATE TABLE IF NOT EXISTS share_of_voice (
        id SERIAL PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id),
        brand_name TEXT NOT NULL,
        normalized_visibility REAL,
        average_positioning REAL,
        weighted_score REAL,
        rank INTEGER,
        timestamp TEXT NOT NULL
    );
    
    -- Saved prompts table
    CREATE TABLE IF NOT EXISTS saved_prompts (
        id SERIAL PRIMARY KEY,
        brand_name TEXT NOT NULL,
        product_name TEXT,
        prompts_json JSONB NOT NULL,
        timestamp TEXT NOT NULL,
        UNIQUE(brand_name, product_name)
    );
    
    -- Cohorts table
    CREATE TABLE IF NOT EXISTS cohorts (
        id SERIAL PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id),
        cohort_name TEXT NOT NULL,
        cohort_description TEXT,
        prompt_count INTEGER,
        cohort_order INTEGER,
        timestamp TEXT NOT NULL
    );
    
    -- Prompts with cohort mapping table
    CREATE TABLE IF NOT EXISTS prompts_cohort_mapping (
        id SERIAL PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES analysis_sessions(session_id),
        cohort_id INTEGER NOT NULL REFERENCES cohorts(id),
        prompt_text TEXT NOT NULL,
        prompt_index INTEGER,
        selected BOOLEAN DEFAULT FALSE,
        timestamp TEXT NOT NULL
    );
    """
    
    logger.info("Copy the above SQL to Supabase SQL Editor to create tables")
    return True

def create_session_id(brand_name: str, product_name: Optional[str] = None) -> str:
    import secrets
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_suffix = secrets.token_hex(2)  # 4-char hex, e.g. "a3f1" — ensures uniqueness even on same-second creation
    if product_name:
        return f"{brand_name.replace(' ', '_')}_{product_name.replace(' ', '_')}_{timestamp}_{unique_suffix}"
    return f"{brand_name.replace(' ', '_')}_{timestamp}_{unique_suffix}"

def create_prompt_id(session_id: str, prompt_index: int) -> str:
    return f"{session_id}_prompt_{prompt_index}"

def save_session(session_id: str, brand_name: str, user_id: str, product_name: Optional[str] = None, 
                 website_url: Optional[str] = None, research_data: Optional[Dict] = None,
                 keywords: Optional[List[str]] = None, industry: Optional[str] = None,
                 project_id: Optional[str] = None, brand_aliases: Optional[List[str]] = None):
    
    try:
        logger.info(f"💾 Saving session {session_id} for brand {brand_name}. Project ID: {project_id}")
        timestamp = datetime.now().isoformat()
        
        data = {
            'session_id': session_id,
            'user_id': user_id,
            'brand_name': brand_name,
            'product_name': product_name,
            'industry': industry,
            'website_url': website_url,
            'timestamp': timestamp,
            'research_data': research_data,
            'keywords': keywords,
            'brand_aliases': brand_aliases,
            # 'project_id': project_id  <-- REMOVED from here
            # Note: We do NOT set 'status' here to avoid overwriting "running" status with "pending"
        }
        
        # Only update project_id if explicitly provided, to avoid overwriting with None
        if project_id is not None:
            data['project_id'] = project_id
        
        # ✅ FIX: Use upsert instead of insert to prevent "duplicate key" errors
        supabase.table('analysis_sessions').upsert(data).execute()
        logger.info(f"✅ Saved/Updated session: {session_id}")
    except Exception as e:
        logger.error(f"Error saving session: {str(e)}")
        raise

def save_llm_response(prompt_id: str, session_id: str, llm_name: str, 
                     prompt_text: str, response_text: str, citations: Optional[List[str]] = None):
    try:
        timestamp = datetime.now().isoformat()
        
        data = {
            'prompt_id': prompt_id,
            'session_id': session_id,
            'llm_name': llm_name,
            'prompt_text': prompt_text,
            'response_text': response_text,
            'citations': citations,
            'timestamp': timestamp
        }
        
        supabase.table('llm_responses').insert(data).execute()
    except Exception as e:
        logger.error(f"Error saving LLM response: {str(e)}")
        raise

def save_scoring_result(prompt_id: str, session_id: str, llm_name: str, scores: Dict[str, Any]):
    try:
        timestamp = datetime.now().isoformat()
        
        data = {
            'prompt_id': prompt_id,
            'session_id': session_id,
            'llm_name': llm_name,
            'brand_mention_score': scores.get('brand_mention_score', 0),
            'position_score': scores.get('position_score', 0),
            'description_richness_score': scores.get('description_richness_score', 0),
            'keyword_strength_score': scores.get('keyword_strength_score', 0),
            'total_score': scores.get('total_score', 0),
            'normalized_visibility': scores.get('normalized_visibility', 0),
            'average_positioning': scores.get('average_positioning', 0),
            'weighted_score': scores.get('weighted_score', 0),
            'brand_position': scores.get('brand_position', 0),
            'total_items': scores.get('total_items', 0),
            'timestamp': timestamp
        }
        
        supabase.table('scoring_results').insert(data).execute()
    except Exception as e:
        logger.error(f"Error saving scoring result: {str(e)}")
        raise

def save_competitors(session_id: str, competitors: list):
    try:
        # Clear existing competitors to prevent duplication on re-runs
        supabase.table('competitors').delete().eq('session_id', session_id).execute()
        
        # Deduplicate while preserving order
        seen = set()
        unique_competitors = []
        for c in competitors:
            # We want to do a case-insensitive deduplication, but preserve original case
            c_lower = str(c).lower().strip()
            if c_lower not in seen and c_lower != "":
                unique_competitors.append(c)
                seen.add(c_lower)
                
        data = [
            {
                'session_id': session_id,
                'competitor_name': competitor,
                'rank': rank
            }
            for rank, competitor in enumerate(unique_competitors, 1)
        ]
        
        if data:
            supabase.table('competitors').insert(data).execute()
        logger.info(f"✓ Saved {len(unique_competitors)} unique competitors for session {session_id}")
    except Exception as e:
        logger.error(f"Error saving competitors: {str(e)}")
        raise

def save_share_of_voice(session_id: str, brand_name: str, sov_scores: Dict[str, Any], rank: int):
    try:
        timestamp = datetime.now().isoformat()
        
        data = {
            'session_id': session_id,
            'brand_name': brand_name,
            'normalized_visibility': sov_scores.get('normalized_visibility', 0),
            'average_positioning': sov_scores.get('average_positioning', 0),
            'weighted_score': sov_scores.get('weighted_score', 0),
            'rank': rank,
            'timestamp': timestamp
        }
        
        supabase.table('share_of_voice').insert(data).execute()
    except Exception as e:
        logger.error(f"Error saving share of voice: {str(e)}")
        raise

def save_brand_score_summary(session_id: str, brand_name: str, summary: Dict[str, Any]):
    try:
        timestamp = datetime.now().isoformat()
        summary_prompt_id = f"{session_id}_summary"
        
        total_prompts = summary.get('total_prompts', 0)
        total_mentions = summary.get('total_mentions', 0)
        mention_rate = summary.get('mention_rate', 0)
        
        mention_based_visibility = mention_rate
        
        data = {
            'prompt_id': summary_prompt_id,
            'session_id': session_id,
            'llm_name': 'SUMMARY',
            'brand_mention_score': total_mentions,
            'position_score': summary.get('avg_position', 0),
            'description_richness_score': 0,
            'keyword_strength_score': 0,
            'total_score': mention_based_visibility,
            'normalized_visibility': mention_based_visibility,
            'average_positioning': summary.get('avg_position', 0),
            'weighted_score': mention_based_visibility,
            'brand_position': 0,
            'total_items': total_prompts,
            'timestamp': timestamp
        }
        
        supabase.table('scoring_results').insert(data).execute()
        logger.info(f"✅ Saved brand score summary for session {session_id}: {mention_based_visibility:.2f}% visibility ({total_mentions}/{total_prompts})")
    except Exception as e:
        logger.error(f"Error saving brand score summary: {str(e)}")
        raise

def get_session_results(session_id: str) -> Dict[str, Any]:
    try:
        # Get session metadata
        session_response = supabase.table('analysis_sessions').select('*').eq('session_id', session_id).execute()
        session = session_response.data[0] if session_response.data else None
        
        if not session:
            logger.warning(f"Session {session_id} not found in database")
            return None
        
        logger.info(f"Found session {session_id}, fetching related data")
        
        # Get LLM responses
        responses_response = supabase.table('llm_responses').select('*').eq('session_id', session_id).execute()
        responses = responses_response.data
        
        # Get scoring results
        scores_response = supabase.table('scoring_results').select('*').eq('session_id', session_id).execute()
        scores = scores_response.data
        
        # Get competitors
        competitors_response = supabase.table('competitors').select('*').eq('session_id', session_id).order('rank').execute()
        competitors = competitors_response.data
        
        # Get Share of Voice
        sov_response = supabase.table('share_of_voice').select('*').eq('session_id', session_id).order('rank').execute()
        sov = sov_response.data
        
        logger.info(f"Session {session_id}: {len(responses or [])} responses, {len(scores or [])} scores, {len(competitors or [])} competitors")
        
        return {
            'session': session,
            'responses': responses,
            'scores': scores,
            'competitors': competitors,
            'share_of_voice': sov
        }
    except Exception as e:
        logger.error(f"Error getting session results: {str(e)}", exc_info=True)
        return None

def get_all_sessions() -> List[Dict[str, Any]]:
    try:
        response = supabase.table('analysis_sessions').select(
            'session_id, brand_name, product_name, timestamp'
        ).order('timestamp', desc=True).execute()
        
        return response.data
    except Exception as e:
        logger.error(f"Error getting all sessions: {str(e)}")
        return []

def get_brand_visibility_history(brand_name: str, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
   
   
    try:
        # Build query for sessions for this brand (and optionally user)
        query = supabase.table('analysis_sessions').select(
            'session_id, brand_name, timestamp'
        ).eq('brand_name', brand_name)

        if user_id:
            query = query.eq('user_id', user_id)

        sessions_response = query.order('timestamp').execute()
        
        sessions = sessions_response.data
        
        if not sessions:
            logger.warning(f"No sessions found for brand: {brand_name} (user_id={user_id})")
            return []
        
        # Optimization: Fetch all scores in one query instead of N+1
        session_ids = [s['session_id'] for s in sessions]
        
        if not session_ids:
             return []
             
        # Batch fetch scores for all sessions in this history
        scores_response = supabase.table('scoring_results').select(
            'session_id, brand_mention_score, average_positioning'
        ).in_('session_id', session_ids).neq('llm_name', 'SUMMARY').execute()
        
        all_scoring_results = scores_response.data or []
        
        # Group scores by session_id for O(1) access
        scores_by_session = {}
        for score in all_scoring_results:
            sid = score['session_id']
            if sid not in scores_by_session:
                scores_by_session[sid] = []
            scores_by_session[sid].append(score)
        rank_response = supabase.table('share_of_voice').select(
            'session_id, brand_name, rank, average_positioning'
        ).in_('session_id', session_ids).execute()
        
        target_brand_low = brand_name.lower().strip()
        ranks_by_session = {}
        for r in (rank_response.data or []):
            if r.get('brand_name', '').lower().strip() == target_brand_low:
                pos = r.get('average_positioning')
                ranks_by_session[r['session_id']] = pos if (pos is not None and pos > 0) else r.get('rank', 0)
        
        result = []
        
        # Process each session in memory using the batched data
        for session in sessions:
            session_id = session['session_id']
            
            # Get pre-fetched scores from our dictionary
            scoring_results = scores_by_session.get(session_id, [])
            
            total_prompts = len(scoring_results)
            mentions = sum(1 for s in scoring_results if s.get('brand_mention_score', 0) > 0)
            
            visibility = (mentions / total_prompts * 100) if total_prompts > 0 else 0
            
            # Use actual competitive rank stored in share_of_voice (average_positioning)
            avg_position = ranks_by_session.get(session_id, 0)

            timestamp = session['timestamp']
            date = timestamp.split('T')[0] if 'T' in timestamp else timestamp.split(' ')[0]
            
            result.append({
                'date': date,
                'timestamp': timestamp,
                'visibility': round(float(visibility), 2),
                'average_position': round(float(avg_position), 2),
                'session_id': session_id,
                'brand_name': brand_name
            })
        
        logger.info(f"✅ Retrieved {len(result)} historical sessions for brand: {brand_name} (user_id={user_id})")
        return result
        
    except Exception as e:
        logger.error(f"❌ Error getting brand visibility history for {brand_name}: {str(e)}")
        return []

def get_llm_aggregate_scores(session_id: str, llm_name: str) -> Dict[str, float]:

    try:
        response = supabase.table('scoring_results').select(
            'normalized_visibility, average_positioning, weighted_score'
        ).eq('session_id', session_id).eq('llm_name', llm_name).execute()
        
        results = response.data
        
        if not results:
            return {
                'avg_visibility': 0,
                'avg_positioning': 0,
                'avg_weighted_score': 0,
                'total_prompts': 0
            }
        
        total_prompts = len(results)
        avg_visibility = sum(r['normalized_visibility'] for r in results) / total_prompts
        
        positioning_scores = [r['average_positioning'] for r in results if r['average_positioning'] > 0]
        if positioning_scores:
            total_points = sum(max(0, 7 - pos) for pos in positioning_scores)
            avg_positioning = total_points * len(positioning_scores)
        else:
            avg_positioning = 0
        
        avg_weighted = sum(r['weighted_score'] for r in results) / total_prompts
        
        return {
            'avg_visibility': round(avg_visibility, 2),
            'avg_positioning': round(avg_positioning, 2),
            'avg_weighted_score': round(avg_weighted, 2),
            'total_prompts': total_prompts
        }
    except Exception as e:
        logger.error(f"Error getting LLM aggregate scores: {str(e)}")
        return {'avg_visibility': 0, 'avg_positioning': 0, 'avg_weighted_score': 0, 'total_prompts': 0}

def get_saved_prompts(brand_name: str, product_name: Optional[str] = None) -> Optional[List[str]]:

    try:
        query = supabase.table('saved_prompts').select('prompts_json').eq('brand_name', brand_name)
        
        if product_name:
            query = query.eq('product_name', product_name)
        else:
            query = query.is_('product_name', 'null')
        
        response = query.execute()
        
        if response.data:
            return response.data[0]['prompts_json']
        return None
    except Exception as e:
        logger.error(f"Error retrieving saved prompts: {str(e)}")
        return None

def save_prompts_to_db(brand_name: str, prompts: List[str], product_name: Optional[str] = None):

    try:
        timestamp = datetime.now().isoformat()
        
        data = {
            'brand_name': brand_name,
            'product_name': product_name,
            'prompts_json': prompts,
            'timestamp': timestamp
        }
        
        # Upsert (insert or update if exists)
        supabase.table('saved_prompts').upsert(data).execute()
    except Exception as e:
        logger.error(f"Error saving prompts: {str(e)}")
        raise

def get_session_results_aggregated(session_id: str):

    try:
        logger.info(f"Fetching aggregated results for session: {session_id}")
        
        # Get session metadata
        session_response = supabase.table('analysis_sessions').select('*').eq('session_id', session_id).execute()
        
        if not session_response.data:
            logger.warning(f"Session {session_id} not found in database")
            return None
        
        session_dict = session_response.data[0]
        brand_name = session_dict.get('brand_name', 'Unknown')
        logger.info(f"Found session {session_id} for brand {brand_name}")

        # Get LLM responses - Optimizing columns to avoid PROTOCOL_ERROR
        llm_response = supabase.table('llm_responses').select(
            'id, prompt_id, llm_name, prompt_text, response_text, citations'
        ).eq('session_id', session_id).order('id').execute()
        llm_rows = llm_response.data
        
        # Get scoring results
        scoring_response = supabase.table('scoring_results').select('*').eq('session_id', session_id).execute()
        scoring_results = scoring_response.data
        
        # Optimize: Group scores by (prompt_id, llm_name) for O(1) lookup
        scores_by_key = {
            (s.get('prompt_id'), s.get('llm_name')): s 
            for s in (scoring_results or [])
        }
        
        # NEW: Fetch Cohorts for this session
        # Ensure get_cohorts_for_session is defined in this file or imported
        cohorts = get_cohorts_for_session(session_id) 
        
        llm_responses = []
        all_citations = []

        for row in (llm_rows or []):
            response_text = row.get('response_text', '')
            prompt_text = row.get('prompt_text', '').strip() or 'Source Unknown'
            llm_name = row.get('llm_name', 'Unknown')
            prompt_id = row.get('prompt_id')

            citations = row.get('citations', []) or []

            visibility_score = 0
            matching_score = scores_by_key.get((prompt_id, llm_name))
            
            if matching_score:
                visibility_score = float(matching_score.get('normalized_visibility', 0))

            llm_responses.append({
                'prompt': prompt_text,
                'response': response_text,
                'llm_name': llm_name,
                'citations': citations,
                'visibility_score': visibility_score
            })
            all_citations.extend(citations)

        # Domain citations
        domain_citations = []
        if all_citations:
            domains = []
            for citation_url in all_citations:
                try:
                    parsed = urlparse(citation_url)
                    domain = parsed.netloc or parsed.path
                    if domain:
                        domains.append(domain.replace('www.', ''))
                except:
                    continue
            
            if domains:
                domain_counts = Counter(domains)
                total_citations = len(domains)
                domain_citations = [
                    {'domain': d, 'citations': c, 'percentage': round((c/total_citations*100), 1)}
                    for d, c in domain_counts.most_common(10)
                ]
        
        # Calculate mention-based visibility metrics
        non_summary_scores = [s for s in scoring_results if s.get('llm_name') != 'SUMMARY']
        
        total_prompts_analyzed = len(non_summary_scores)
        total_mentions = sum(1 for s in non_summary_scores if s.get('brand_mention_score', 0) > 0)
        
        positioned_scores = [s for s in non_summary_scores if s.get('average_positioning', 0) > 0]
        if positioned_scores:
            total_points = sum(max(0, 7 - s.get('average_positioning', 0)) for s in positioned_scores)
            avg_position = total_points * total_mentions
        else:
            avg_position = 0
        
        mention_based_visibility = (total_mentions / total_prompts_analyzed * 100) if total_prompts_analyzed > 0 else 0
        
        # Share of Voice
        sov_response = supabase.table('share_of_voice').select('*').eq('session_id', session_id).order('rank').execute()
        sov_rows = sov_response.data or []
        
        brand_scores = []
        share_of_voice = []

        total_sov_mass = 0
        temp_sov_data = []

        if sov_rows:
            for row in sov_rows:
                mass = float(row.get('normalized_visibility', 0))
                total_sov_mass += mass
                temp_sov_data.append(row)
        else:
            total_sov_mass = mention_based_visibility
            temp_sov_data.append({
                'brand_name': brand_name,
                'normalized_visibility': mention_based_visibility,
                'average_positioning': avg_position,
                'total_mentions': total_mentions
            })

        # Get previous SOV data once before the loop
        user_id = session_dict.get('user_id')
        prev_sov = get_previous_sov_data(brand_name, user_id, session_id)

        for r in temp_sov_data:
            brand = r.get('brand_name', 'Unknown')
            sov_visibility = float(r.get('normalized_visibility', 0))
            
            if total_sov_mass > 0:
                pie_slice_percentage = (sov_visibility / total_sov_mass) * 100
            else:
                pie_slice_percentage = 0

            if brand == brand_name:
                display_visibility = mention_based_visibility
            else:
                display_visibility = sov_visibility
            
            # Get previous average position for delta calculation
            prev_data = next((p for p in prev_sov if p.get('brand_name') == brand), None)
            prev_avg_pos = float(prev_data.get('average_positioning', 0)) if prev_data else 0

            brand_scores.append({
                'brand': brand,
                'mention_count': total_mentions if brand == brand_name else r.get('rank', 0),
                'average_position': float(r.get('average_positioning', 0)),
                'prev_average_position': prev_avg_pos,
                'visibility_score': display_visibility,
                'mention_rate': display_visibility / 100,
                'rank': r.get('rank', 0)
            })
            
            share_of_voice.append({
                'brand': brand,
                'percentage': round(pie_slice_percentage, 1),
                'mention_count': r.get('total_mentions', 0)
            })

        # Competitors
        competitors_response = supabase.table('competitors').select('competitor_name').eq('session_id', session_id).order('rank').execute()
        competitors = [row['competitor_name'] for row in (competitors_response.data or [])]
        
        return {
            'session_id': session_id,
            'brand_name': brand_name,
            'num_prompts': total_prompts_analyzed,
            'brand_scores': brand_scores,
            'share_of_voice': share_of_voice,
            'llm_responses': llm_responses,
            'domain_citations': domain_citations,
            'competitors': competitors,
            'cohorts': cohorts, # ✅ Added cohorts here
            'created_at': session_dict.get('timestamp', ''),
            'average_visibility_score': mention_based_visibility,
            'average_position': avg_position,
            'average_mentions': total_mentions,
            'session_metadata': {
                'user_id': session_dict.get('user_id'),
                'product_name': session_dict.get('product_name'),
                'website_url': session_dict.get('website_url'),
                'keywords': session_dict.get('keywords')
            }
        }
    except Exception as e:
        logger.error(f"Error getting aggregated results: {e}", exc_info=True)
        return None

def get_all_unique_brands(user_id: Optional[str] = None):
    """Get unique brand names. Scoped to user_id to prevent cross-tenant data leaks."""
    try:
        query = supabase.table('analysis_sessions').select('brand_name')
        if user_id:
            query = query.eq('user_id', user_id)
        response = query.execute()
        brands = list(set(row['brand_name'] for row in response.data))
        return sorted(brands)
    except Exception as e:
        logger.error(f"Error getting unique brands: {str(e)}")
        return []

def get_recent_sessions_by_brand(brand_name: str, limit: int = 20, user_id: Optional[str] = None):
    """Get recent sessions for a brand. Scoped to user_id to prevent cross-tenant data leaks."""
    try:
        query = supabase.table('analysis_sessions').select(
            'session_id, brand_name, product_name, website_url, timestamp'
        ).eq('brand_name', brand_name)
        if user_id:
            query = query.eq('user_id', user_id)
        response = query.order('timestamp', desc=True).limit(limit).execute()
        return response.data
    except Exception as e:
        logger.error(f"Error getting recent sessions by brand: {str(e)}")
        return []

def get_saved_prompts_for_analysis(session_id: str):
    try:
        response = supabase.table('llm_responses').select('prompt_text').eq('session_id', session_id).order('timestamp').execute()
        
        # Get unique prompts
        prompts = list(set(row['prompt_text'] for row in response.data))
        return prompts
    except Exception as e:
        logger.error(f"Error getting saved prompts for analysis: {str(e)}")
        return []

def get_visibility_history_for_same_prompts(brand_name: str, product_name: str, prompts: list, user_id: Optional[str] = None):
    """Get visibility history for same prompts. Scoped to user_id to prevent cross-tenant data leaks."""
    try:
        if not prompts or not brand_name:
            logger.warning("No prompts or brand_name provided for same prompts history")
            return []
        
        # Get all sessions for this brand, scoped to the authenticated user
        query = supabase.table('analysis_sessions').select(
            'session_id, timestamp'
        ).eq('brand_name', brand_name)
        if user_id:
            query = query.eq('user_id', user_id)
        sessions_response = query.order('timestamp').execute()
        
        sessions = sessions_response.data
        
        if not sessions:
            return []
            
        session_ids = [s['session_id'] for s in sessions]
        
        # Batch fetch LLM responses to find prompt_ids for these specific prompts across all sessions
        responses_res = supabase.table('llm_responses').select(
            'session_id, prompt_id, prompt_text'
        ).in_('session_id', session_ids).in_('prompt_text', prompts).execute()
        
        # Group prompt_ids by session_id
        prompt_ids_by_session = {}
        for r in (responses_res.data or []):
            sid = r['session_id']
            pid = r['prompt_id']
            if sid not in prompt_ids_by_session:
                prompt_ids_by_session[sid] = []
            prompt_ids_by_session[sid].append(pid)
            
        # Collect all relevant prompt_ids for batch fetching scores
        all_relevant_pids = []
        for pids in prompt_ids_by_session.values():
            all_relevant_pids.extend(pids)
            
        if not all_relevant_pids:
            return []
            
        # Batch fetch scoring results for these sessions and prompts
        # We filter by session_ids AND the specific prompt_ids we care about
        scores_res = supabase.table('scoring_results').select(
            'session_id, prompt_id, brand_mention_score'
        ).in_('session_id', session_ids).in_('prompt_id', all_relevant_pids).neq('llm_name', 'SUMMARY').execute()
        
        # Group scores by session_id
        scores_by_session = {}
        for s in (scores_res.data or []):
            sid = s['session_id']
            pid = s['prompt_id']
            # Only include if it matches a prompt_id for THIS session
            if pid in prompt_ids_by_session.get(sid, []):
                if sid not in scores_by_session:
                    scores_by_session[sid] = []
                scores_by_session[sid].append(s)
            
        chart_data = []
        
        for session in sessions:
            session_id = session['session_id']
            
            # Get pre-fetched scores for this session's relevant prompts
            scoring_results = scores_by_session.get(session_id, [])
            
            if not scoring_results:
                continue
                
            total_prompts = len(scoring_results)
            mentions = sum(1 for s in scoring_results if s.get('brand_mention_score', 0) > 0)
            
            visibility = (mentions / total_prompts * 100) if total_prompts > 0 else 0
            
            timestamp = session['timestamp']
            if 'T' in timestamp:
                date_display = timestamp.split('T')[0]
                time_display = timestamp.split('T')[1][:5]
            else:
                date_display = timestamp.split(' ')[0]
                time_display = timestamp.split(' ')[1][:5] if ' ' in timestamp else '00:00'
            
            chart_data.append({
                'date': f"{date_display} {time_display}",
                'visibility': round(visibility, 2),
                'timestamp': timestamp,
                'session_id': session_id
            })
        
        logger.info(f"✅ Found {len(chart_data)} session points for same prompts history (brand: {brand_name})")
        return chart_data
        
    except Exception as e:
        logger.error(f"Error in get_visibility_history_for_same_prompts: {str(e)}", exc_info=True)
        return []

def get_product_specific_visibility_history(brand_name: str, product_name: str, user_id: Optional[str] = None):
    try:
        # Build query for sessions for brand+product (optionally scoped to user)
        query = supabase.table('analysis_sessions').select(
            'session_id, timestamp'
        ).eq('brand_name', brand_name).eq('product_name', product_name)

        if user_id:
            query = query.eq('user_id', user_id)

        sessions_response = query.order('timestamp').execute()
        
        sessions = sessions_response.data
        
        if not sessions:
            return []
            
        # Optimization: Fetch all scores in one query instead of N+1
        session_ids = [s['session_id'] for s in sessions]
        
        # Batch fetch all normalized visibility scores for these sessions
        scores_response = supabase.table('scoring_results').select(
            'session_id, normalized_visibility'
        ).in_('session_id', session_ids).execute()
        
        all_scores = scores_response.data or []
        
        # Group by session_id
        scores_by_session = {}
        for score in all_scores:
            sid = score['session_id']
            if sid not in scores_by_session:
                scores_by_session[sid] = []
            scores_by_session[sid].append(score)
        
        history = {}
        
        # Process each session using the batched data
        for session in sessions:
            session_id = session['session_id']
            
            # Get pre-fetched scores
            scoring_results = scores_by_session.get(session_id, [])
            
            if scoring_results:
                avg_visibility = sum(s['normalized_visibility'] for s in scoring_results) / len(scoring_results)
                
                timestamp = session['timestamp']
                date = timestamp.split('T')[0] if 'T' in timestamp else timestamp.split(' ')[0]
                
                if date not in history:
                    history[date] = []
                history[date].append(avg_visibility)
        
        chart_data = [
            {
                'date': date,
                'visibility': round(sum(scores) / len(scores), 2),
                'timestamp': date
            }
            for date, scores in sorted(history.items())
        ]
        
        return chart_data
        
    except Exception as e:
        logger.error(f"Error getting product visibility history: {str(e)}")
        return []

def get_recent_sessions(limit=10):
    try:
        response = supabase.table('analysis_sessions').select(
            'session_id, brand_name, timestamp, product_name, website_url'
        ).order('timestamp', desc=True).limit(limit).execute()
        
        return response.data
    except Exception as e:
        logger.error(f"Error getting recent sessions: {str(e)}")
        return []

def save_cohorts(session_id: str, cohorts: List[Dict]) -> List[int]:
    try:
        session_check = supabase.table('analysis_sessions').select('session_id').eq('session_id', session_id).execute()
        if not session_check.data:
            logger.error(f"❌ Session {session_id} does NOT exist in database. Cannot save cohorts!")
            raise Exception(f"Session {session_id} must be saved to database before creating cohorts")
        
        timestamp = datetime.now().isoformat()
        cohort_ids = []
        
        for idx, cohort in enumerate(cohorts):
            data = {
                'session_id': session_id,
                'cohort_name': cohort['name'],
                'cohort_description': cohort.get('description', ''),
                'prompt_count': cohort.get('prompt_count', 3),
                'cohort_order': idx,
                'timestamp': timestamp
            }
            
            response = supabase.table('cohorts').insert(data).execute()
            if response.data:
                cohort_ids.append(response.data[0]['id'])
        
        logger.info(f"✅ Saved {len(cohorts)} cohorts for session {session_id}")
        return cohort_ids
        
    except Exception as e:
        logger.error(f"Error saving cohorts: {str(e)}")
        logger.error(f"  Session ID: {session_id}")
        logger.error(f"  Cohort count: {len(cohorts) if cohorts else 0}")
        raise


def save_prompts_with_cohorts(session_id: str, cohort_prompts: List[Dict]):
    try:
        timestamp = datetime.now().isoformat()
        
        all_data = []
        prompt_index = 0
        
        for cohort_data in cohort_prompts:
            cohort_id = cohort_data['cohort_id']
            prompts = cohort_data['prompts']
            
            for prompt_text in prompts:
                all_data.append({
                    'session_id': session_id,
                    'cohort_id': cohort_id,
                    'prompt_text': prompt_text,
                    'prompt_index': prompt_index,
                    'selected': False,
                    'timestamp': timestamp
                })
                prompt_index += 1
        
        if all_data:
            supabase.table('prompts_cohort_mapping').insert(all_data).execute()
        
        logger.info(f"✅ Saved {prompt_index} prompts with cohort mappings for session {session_id}")
        
    except Exception as e:
        logger.error(f"Error saving prompts with cohorts: {str(e)}")
        raise

def get_cohorts_for_session(session_id: str) -> List[Dict]:
    try:
        # Get cohorts
        cohorts_response = supabase.table('cohorts').select('*').eq('session_id', session_id).order('cohort_order').execute()
        
        logger.info(f"📊 Retrieved {len(cohorts_response.data)} cohorts for session {session_id}")
        
        if not cohorts_response.data:
            logger.warning(f"⚠️ No cohorts found for session {session_id}")
            return []
        
        # Optimize: Fetch ALL prompts for this session in one go to avoid N+1 requests
        # This prevents "COMPRESSION_ERROR" and connection termination issues
        all_prompts_response = supabase.table('prompts_cohort_mapping').select(
            'cohort_id, prompt_text, prompt_index, selected'
        ).eq('session_id', session_id).order('prompt_index').execute()
        
        all_prompts = all_prompts_response.data or []
        
        # Group prompts by cohort_id
        prompts_by_cohort = {}
        for p in all_prompts:
            cid = p['cohort_id']
            if cid not in prompts_by_cohort:
                prompts_by_cohort[cid] = []
            prompts_by_cohort[cid].append(p)
            
        logger.info(f"✅ Retrieved {len(all_prompts)} total prompts for session")
        
        cohorts = []
        for cohort_row in cohorts_response.data:
            cohort_id = cohort_row['id']
            
            # Get prompts from memory
            prompts = prompts_by_cohort.get(cohort_id, [])
             
            # Ensure prompts are properly formatted for frontend
            formatted_prompts = []
            for prompt in prompts:
                formatted_prompts.append({
                    'prompt_text': prompt.get('prompt_text', ''),
                    'category': None  # Add category if needed
                })
            
            cohorts.append({
                'id': cohort_id,
                'name': cohort_row['cohort_name'],
                'description': cohort_row['cohort_description'],
                'prompt_count': len(formatted_prompts),
                'prompts': formatted_prompts
            })
        
        logger.info(f"✅ Successfully retrieved {len(cohorts)} cohorts with prompts")
        return cohorts
        
    except Exception as e:
        logger.error(f"❌ Error retrieving cohorts: {str(e)}")
        logger.error(f"   Stack trace: {traceback.format_exc()}")
        return []

def update_prompt_selection(session_id: str, prompt_indices: List[int], selected: bool = True):
    try:
        supabase.table('prompts_cohort_mapping').update({
            'selected': selected
        }).eq('session_id', session_id).in_('prompt_index', prompt_indices).execute()
        
        logger.info(f"✅ Updated selection for {len(prompt_indices)} prompts")
        
    except Exception as e:
        logger.error(f"Error updating prompt selection: {str(e)}")
        raise

def save_custom_cohort(session_id: str, cohort_name: str, cohort_description: str, cohort_order: int) -> int:
    try:
        timestamp = datetime.now().isoformat()
        
        data = {
            'session_id': session_id,
            'cohort_name': cohort_name,
            'cohort_description': cohort_description,
            'prompt_count': 5,
            'cohort_order': cohort_order,
            'timestamp': timestamp
        }
        
        response = supabase.table('cohorts').insert(data).execute()
        
        if response.data:
            cohort_id = response.data[0]['id']
            logger.info(f"✅ Saved custom cohort: {cohort_name} (ID: {cohort_id})")
            return cohort_id
        return -1
        
    except Exception as e:
        logger.error(f"Error saving custom cohort: {str(e)}")
        return -1

def save_custom_prompts(session_id: str, cohort_id: int, prompts: List[str], start_index: int = 0):
    try:
        timestamp = datetime.now().isoformat()
        
        data = [
            {
                'session_id': session_id,
                'cohort_id': cohort_id,
                'prompt_text': prompt_text,
                'prompt_index': start_index + idx,
                'selected': True,
                'timestamp': timestamp
            }
            for idx, prompt_text in enumerate(prompts)
        ]
        
        supabase.table('prompts_cohort_mapping').insert(data).execute()
        logger.info(f"✅ Saved {len(prompts)} custom prompts for cohort {cohort_id}")
        
    except Exception as e:
        logger.error(f"Error saving custom prompts: {str(e)}")
        raise

def get_prompt_count_for_cohort(session_id: str, cohort_id: int) -> int:
    try:
        response = supabase.table('prompts_cohort_mapping').select(
            'id', count='exact'
        ).eq('session_id', session_id).eq('cohort_id', cohort_id).eq('selected', True).execute()
        
        return response.count if response.count else 0
        
    except Exception as e:
        logger.error(f"Error getting prompt count: {str(e)}")
        return 0

def update_cohort_selection(session_id: str, cohort_id: int, selected: bool):
    try:
        if not selected:
            supabase.table('prompts_cohort_mapping').update({
                'selected': False
            }).eq('session_id', session_id).eq('cohort_id', cohort_id).execute()
        
        logger.info(f"Updated cohort {cohort_id} selection: {selected}")
        
    except Exception as e:
        logger.error(f"Error updating cohort selection: {str(e)}")
        raise

def get_selected_cohort_count(session_id: str) -> int:
    try:
        response = supabase.table('prompts_cohort_mapping').select(
            'cohort_id'
        ).eq('session_id', session_id).eq('selected', True).execute()
        
        unique_cohorts = set(row['cohort_id'] for row in response.data)
        return len(unique_cohorts)
        
    except Exception as e:
        logger.error(f"Error getting selected cohort count: {str(e)}")
        return 0

def get_selected_prompts(session_id: str) -> List[str]:
    try:
        response = supabase.table('prompts_cohort_mapping').select(
            'prompt_text'
        ).eq('session_id', session_id).eq('selected', True).order('prompt_index').execute()
        
        return [row['prompt_text'] for row in response.data]
        
    except Exception as e:
        logger.error(f"Error retrieving selected prompts: {str(e)}")
        return []


# ============= AUTHENTICATION FUNCTIONS =============

def signup_user(email: str, password_hash: str) -> Optional[str]:
    try:
        data = {
            'email': email,
            'password_hash': password_hash,
            'subscription_plan': 'free',
            'subscription_status': 'active',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        
        response = supabase.table('users').insert(data).execute()
        user_id = response.data[0]['id'] if response.data else None
        
        if user_id:
            logger.info(f"✅ User registered: {email} on free plan")
        
        return user_id
    except Exception as e:
        logger.error(f"Error registering user: {str(e)}")
        raise


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    try:
        response = supabase.table('users').select('*').eq('email', email).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error retrieving user: {str(e)}")
        return None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = supabase.table('users').select(
            'id, email, role, is_suspended, credits_remaining, credits_total, created_at, subscription_plan, subscription_status, subscription_start, subscription_end, billing_cycle'
        ).eq('id', user_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error retrieving user: {str(e)}")
        return None


def activate_user_subscription(user_id: str, plan_name: str, billing_cycle: str, razorpay_payment_id: str) -> bool:
    """
    Updates the users table with subscription details.
    Calculates subscription_end based on billing_cycle (monthly = +30 days, yearly = +365 days).
    """
    try:
        from datetime import timezone
        now = datetime.now(timezone.utc)
        days = 365 if billing_cycle.lower() == "yearly" else 30
        subscription_end = (now + timedelta(days=days)).isoformat()

        supabase.table('users').update({
            'subscription_plan': plan_name,
            'subscription_status': 'active',
            'subscription_start': now.isoformat(),
            'subscription_end': subscription_end,
            'billing_cycle': billing_cycle,
            'razorpay_payment_id': razorpay_payment_id,
            'updated_at': now.isoformat()
        }).eq('id', user_id).execute()

        logger.info(f"✅ Subscription activated for user {user_id}: {plan_name} ({billing_cycle}) until {subscription_end}")
        return True
    except Exception as e:
        logger.error(f"❌ Error activating subscription for user {user_id}: {str(e)}")
        return False


def save_payment_transaction(
    user_id: str,
    user_email: str,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
    plan_name: str,
    billing_cycle: str,
    subscription_end: str,
    amount_paise: int = 0,
    currency: str = "INR"
) -> bool:
    """
    Saves an immutable audit record to the payment_transactions table.
    This provides idempotency: if razorpay_payment_id already exists (UNIQUE), the insert will fail.
    Snapshots the actual charged amount (in paise) and currency for audit and reconciliation.
    """
    try:
        supabase.table('payment_transactions').insert({
            'user_id': user_id,
            'user_email': user_email,
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature,
            'plan_name': plan_name,
            'billing_cycle': billing_cycle,
            'status': 'verified',
            'subscription_end': subscription_end,
            'amount_paise': amount_paise,
            'currency': currency,
        }).execute()
        logger.info(f"✅ Payment transaction saved for user {user_id}, payment {razorpay_payment_id}, amount={amount_paise} {currency}")
        return True
    except Exception as e:
        logger.error(f"❌ Error saving payment transaction: {str(e)}")
        # If the error is a unique-constraint violation the payment was already processed
        raise


def get_subscription_status(user_id: str) -> Dict[str, Any]:
    """
    Returns the subscription status for a user.
    Free plan is active by default without requiring an expiration date.
    Paid plans require subscription_status == 'active' AND subscription_end in the future.
    """
    try:
        from datetime import timezone
        response = supabase.table('users').select(
            'subscription_plan, subscription_status, subscription_start, subscription_end, billing_cycle'
        ).eq('id', user_id).execute()

        if not response.data:
            return {"is_active": True, "subscription_plan": "free", "subscription_status": "active", "subscription_end": None}

        user = response.data[0]
        raw_plan = user.get('subscription_plan')
        plan = (raw_plan or 'free').lower().strip()
        status = user.get('subscription_status') or ('active' if plan == 'free' else 'inactive')
        sub_end_str = user.get('subscription_end')

        is_active = False
        if plan == 'free':
            # Free tier users are always active unless explicitly marked inactive or cancelled
            is_active = (status not in ('cancelled', 'suspended', 'inactive'))
            if is_active:
                status = 'active'
        elif status == 'active' and sub_end_str:
            try:
                # Handle both offset-aware and naive ISO strings
                sub_end = datetime.fromisoformat(sub_end_str.replace('Z', '+00:00'))
                if sub_end.tzinfo is None:
                    sub_end = sub_end.replace(tzinfo=timezone.utc)
                is_active = sub_end > datetime.now(timezone.utc)
            except Exception:
                is_active = False

        return {
            "is_active": is_active,
            "subscription_plan": plan,
            "subscription_status": status,
            "subscription_start": user.get('subscription_start'),
            "subscription_end": sub_end_str,
            "billing_cycle": user.get('billing_cycle'),
        }
    except Exception as e:
        logger.error(f"Error getting subscription status for user {user_id}: {str(e)}")
        return {"is_active": False, "subscription_plan": None, "subscription_end": None}


def get_user_sessions(user_id: str) -> List[Dict[str, Any]]:
    try:
        response = supabase.table('analysis_sessions').select('*').eq('user_id', user_id).order('timestamp', desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Error retrieving user sessions: {str(e)}")
        return []

def duplicate_session_cohorts(parent_session_id: str, new_session_id: str):
 
    try:
        # 1. Get all cohorts from the parent session
        parent_cohorts = supabase.table('cohorts').select('*').eq('session_id', parent_session_id).execute()
        
        if not parent_cohorts.data:
            logger.warning(f"No cohorts found to duplicate for session {parent_session_id}")
            return

        # 2. Iterate and copy each cohort
        for old_cohort in parent_cohorts.data:
            cohort_data = {
                'session_id': new_session_id,
                'cohort_name': old_cohort['cohort_name'],
                'cohort_description': old_cohort.get('cohort_description'),
                'prompt_count': old_cohort.get('prompt_count'),
                'cohort_order': old_cohort.get('cohort_order'),
                'timestamp': datetime.now().isoformat()
            }
            
            # Insert new cohort and get its ID
            new_cohort_res = supabase.table('cohorts').insert(cohort_data).execute()
            
            if new_cohort_res.data:
                new_cohort_id = new_cohort_res.data[0]['id']
                old_cohort_id = old_cohort['id']
                
                # 3. Get all prompts for this cohort
                old_prompts = supabase.table('prompts_cohort_mapping')\
                    .select('*').eq('cohort_id', old_cohort_id).execute()
                
                if old_prompts.data:
                    new_prompts_data = []
                    for prompt in old_prompts.data:
                        new_prompts_data.append({
                            'session_id': new_session_id,
                            'cohort_id': new_cohort_id,
                            'prompt_text': prompt['prompt_text'],
                            'prompt_index': prompt['prompt_index'],
                            'selected': False,
                            'timestamp': datetime.now().isoformat()
                        })
                    
                    # Bulk insert prompts
                    if new_prompts_data:
                        supabase.table('prompts_cohort_mapping').insert(new_prompts_data).execute()
        
        logger.info(f"Successfully duplicated cohorts from {parent_session_id} to {new_session_id}")

    except Exception as e:
        logger.error(f"Error duplicating cohorts: {str(e)}")

def duplicate_session_competitors(parent_session_id: str, new_session_id: str):
    """Copies competitors from one session to another to ensure they are carried forward."""
    try:
        # Get competitors from parent
        response = supabase.table('competitors').select('competitor_name, rank').eq('session_id', parent_session_id).order('rank').execute()
        
        if response.data:
            new_data = [
                {
                    'session_id': new_session_id,
                    'competitor_name': row['competitor_name'],
                    'rank': row['rank']
                }
                for row in response.data
            ]
            supabase.table('competitors').insert(new_data).execute()
            logger.info(f"✅ Duplicated {len(new_data)} competitors from {parent_session_id} to {new_session_id}")
            return True
        return False
    except Exception as e:
        logger.error(f"❌ Error duplicating competitors: {str(e)}")
        return False


# --- PROJECT MANAGEMENT ---

def create_project(user_id: str, name: str, website_url: Optional[str] = None, 
                   industry: Optional[str] = None, update_frequency: str = '24h') -> Optional[Dict[str, Any]]:
   
    try:
        data = {
            'user_id': user_id,
            'name': name,
            'website_url': website_url,
            'industry': industry,
            'update_frequency': update_frequency,
            'is_active': False,  # User must explicitly enable scheduling via the toggle
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat()
        }
        response = supabase.table('projects').insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error creating project: {str(e)}")
        return None

def get_user_projects(user_id: str) -> List[Dict[str, Any]]:
    
    try:
        response = supabase.table('projects').select('*').eq('user_id', user_id).order('created_at', desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Error retrieving user projects: {str(e)}")
        return []

def get_project_by_id(project_id: str) -> Optional[Dict[str, Any]]:
   
    try:
        response = supabase.table('projects').select('*').eq('id', project_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        logger.error(f"Error retrieving project {project_id}: {str(e)}")
        return None

def update_project(project_id: str, update_data: Dict[str, Any]) -> bool:
    
    try:
        update_data['updated_at'] = datetime.now().isoformat()
        supabase.table('projects').update(update_data).eq('id', project_id).execute()
        return True
    except Exception as e:
        logger.error(f"Error updating project {project_id}: {str(e)}")
        return False

def delete_project(project_id: str) -> bool:
    
    try:
        logger.info(f"🗑️ Attempting to delete project {project_id} and all its data")
        
        # 1. Get all session IDs associated with this project
        sessions_res = supabase.table('analysis_sessions').select('session_id').eq('project_id', project_id).execute()
        session_ids = [s['session_id'] for s in (sessions_res.data or [])]
        
        if session_ids:
            logger.info(f"  Found {len(session_ids)} sessions to delete")
            
            # 2. Delete all related data for these sessions
            # We must be thorough because foreign keys might not cascade if not set up that way
            try:
                supabase.table('llm_responses').delete().in_('session_id', session_ids).execute()
                supabase.table('scoring_results').delete().in_('session_id', session_ids).execute()
                supabase.table('competitors').delete().in_('session_id', session_ids).execute()
                supabase.table('share_of_voice').delete().in_('session_id', session_ids).execute()
                supabase.table('prompts_cohort_mapping').delete().in_('session_id', session_ids).execute()
                supabase.table('cohorts').delete().in_('session_id', session_ids).execute()
                # saved_prompts are not linked to session_id, but prompt mappings are.
            except Exception as e:
                logger.warning(f"  Partial failure clearing session children (might be handled by cascade): {e}")

            # 3. Delete the sessions themselves
            supabase.table('analysis_sessions').delete().in_('session_id', session_ids).execute()
            logger.info("  Sessions deleted")
            
        # 4. Delete the project
        # This should cascade to monitored_prompts, monitored_competitors, daily_brand_metrics
        supabase.table('projects').delete().eq('id', project_id).execute()
        
        logger.info(f"✅ Project {project_id} deleted successfully")
        return True
    except Exception as e:
        logger.error(f"Error deleting project {project_id}: {str(e)}")
        return False

# --- MONITORED ENTITIES MANAGEMENT ---

def add_monitored_prompts(project_id: str, prompts: List[str]) -> bool:
    
    try:
        data = [
            {'project_id': project_id, 'prompt_text': prompt, 'is_active': True}
            for prompt in prompts
        ]
        supabase.table('monitored_prompts').insert(data).execute()
        return True
    except Exception as e:
        logger.error(f"Error adding monitored prompts: {str(e)}")
        return False

def get_monitored_prompts(project_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
   
    try:
        query = supabase.table('monitored_prompts').select('*').eq('project_id', project_id)
        if active_only:
            query = query.eq('is_active', True)
        response = query.order('created_at', desc=True).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Error retrieving monitored prompts: {str(e)}")
        return []

def add_monitored_competitors(project_id: str, competitor_names: List[str]) -> bool:
    
    try:
        data = [
            {'project_id': project_id, 'name': name}
            for name in competitor_names
        ]
        supabase.table('monitored_competitors').insert(data).execute()
        return True
    except Exception as e:
        logger.error(f"Error adding monitored competitors: {str(e)}")
        return False

def get_monitored_competitors(project_id: str) -> List[Dict[str, Any]]:
    
    try:
        response = supabase.table('monitored_competitors').select('*').eq('project_id', project_id).execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Error retrieving monitored competitors: {str(e)}")
        return []

# --- HISTORICAL AGGREGATED METRICS ---

def get_project_dashboard_metrics(project_id: str, days: int = 30) -> List[Dict[str, Any]]:
    try:
        start_date = (datetime.now() - timedelta(days=days)).date().isoformat()
        response = supabase.table('daily_brand_metrics')\
            .select('*')\
            .eq('project_id', project_id)\
            .gte('date', start_date)\
            .order('date')\
            .execute()
        return response.data if response.data else []
    except Exception as e:
        logger.error(f"Error fetching dashboard metrics: {str(e)}")
        return []

def replace_session_competitors(session_id: str, competitors: list):
    """Deletes existing competitors for a session and adds new ones."""
    try:
        supabase.table('competitors').delete().eq('session_id', session_id).execute()
        if competitors:
            data = [{'session_id': session_id, 'competitor_name': c, 'rank': i+1} for i, c in enumerate(competitors)]
            supabase.table('competitors').insert(data).execute()
        return True
    except Exception as e:
        logger.error(f"Error replacing competitors: {str(e)}")
        raise

def clear_session_metrics(session_id: str):
    """Clears scoring results to prepare for re-calculation."""
    try:
        supabase.table('scoring_results').delete().eq('session_id', session_id).execute()
        supabase.table('share_of_voice').delete().eq('session_id', session_id).execute()
    except Exception as e:
        logger.error(f"Error clearing metrics: {str(e)}")
        raise

# Initialize database on module import
init_database()

def get_detailed_citation_analytics(session_id: str) -> Dict[str, Any]:
    try:
        # Get LLM responses - Optimizing columns to avoid PROTOCOL_ERROR
        llm_response = supabase.table('llm_responses').select(
            'llm_name, prompt_text, timestamp, citations'
        ).eq('session_id', session_id).execute()
        llm_rows = llm_response.data
        
        if not llm_rows:
            return {'citations': []}
            
        domain_stats = {}
        total_session_citations = 0
        
        for row in llm_rows:
            llm_name = row.get('llm_name', 'Unknown')
            prompt_text = row.get('prompt_text', '')
            timestamp = row.get('timestamp', '')
            citations = row.get('citations', []) or []
            
            for url in citations:
                try:
                    parsed = urlparse(url)
                    domain = parsed.netloc or parsed.path
                    domain = domain.replace('www.', '')
                    
                    if not domain:
                        continue
                        
                    if domain not in domain_stats:
                        domain_stats[domain] = {
                            'domain': domain,
                            'total_citations': 0,
                            'urls': [], # List of distinct URL objects
                            'llms': set(),
                            'competitors': [], # Placeholder for now
                            'first_seen': timestamp
                        }
                    
                    stats = domain_stats[domain]
                    stats['total_citations'] += 1
                    total_session_citations += 1
                    stats['llms'].add(llm_name)
                    
                    # Add URL details if unique
                    existing_url = next((u for u in stats['urls'] if u['url'] == url), None)
                    if not existing_url:
                        stats['urls'].append({
                            'url': url,
                            'prompt': prompt_text,
                            'llm': llm_name,
                            'date': timestamp
                        })
                    else:
                        # If existing but from different prompt/llm, maybe just track it? 
                        # For now, unique URLs are key.
                        pass
                        
                except Exception as e:
                    continue
        
        # Format for frontend
        results = []
        for domain, stats in domain_stats.items():
            percentage = (stats['total_citations'] / total_session_citations * 100) if total_session_citations > 0 else 0
            results.append({
                'domain': domain,
                'count': stats['total_citations'],
                'percentage': round(percentage, 1),
                'urls': stats['urls'],
                'llms': list(stats['llms']),
                'competitors': [], 
                'type': 'Other',
                'date': stats['first_seen'] # Rough approx
            })
            
        # Sort by count desc
        results.sort(key=lambda x: x['count'], reverse=True)
        
        return {'citations': results, 'total_citations': total_session_citations}

    except Exception as e:
        logger.error(f"Error getting citation analytics:{e}")
        return {'citations': [], 'total_citations': 0}

def get_brand_citation_repository(brand_name: str, user_id: str) -> Dict[str, Any]:
    """
    Aggregates citations from all analysis sessions for a specific brand and user.
    Creates a 'repository' view with frequency tracking.
    """
    try:
        # 1. Get all session IDs for this brand and user
        sessions_response = supabase.table('analysis_sessions').select('session_id').eq('brand_name', brand_name).eq('user_id', user_id).execute()
        session_ids = [s['session_id'] for s in (sessions_response.data or [])]
        
        if not session_ids:
            return {'citations': [], 'total_citations': 0}
            
        # 2. Fetch LLM responses for all these sessions in batch - Optimizing columns
        llm_response = supabase.table('llm_responses').select(
            'llm_name, prompt_text, timestamp, citations'
        ).in_('session_id', session_ids).execute()
        llm_rows = llm_response.data
        
        if not llm_rows:
            return {'citations': []}
            
        domain_stats = {}
        total_brand_citations = 0
        
        for row in llm_rows:
            llm_name = row.get('llm_name', 'Unknown')
            prompt_text = row.get('prompt_text', '')
            timestamp = row.get('timestamp', '')
            citations = row.get('citations', []) or []
            
            for url in citations:
                try:
                    parsed = urlparse(url)
                    domain = parsed.netloc or parsed.path
                    domain = domain.replace('www.', '')
                    
                    if not domain:
                        continue
                        
                    if domain not in domain_stats:
                        domain_stats[domain] = {
                            'domain': domain,
                            'total_citations': 0,
                            'urls': [], # List of distinct URL objects
                            'llms': set(),
                            'competitors': set(),
                            'first_seen': timestamp
                        }
                    
                    stats = domain_stats[domain]
                    stats['total_citations'] += 1
                    total_brand_citations += 1
                    stats['llms'].add(llm_name)
                    
                    # Add URL details if unique
                    existing_url = next((u for u in stats['urls'] if u['url'] == url), None)
                    if not existing_url:
                        stats['urls'].append({
                            'url': url,
                            'prompt': prompt_text,
                            'llm': llm_name,
                            'date': timestamp
                        })
                    else:
                        # If existing, we could potentially update metadata or count frequency per URL
                        # For now, we follow the session-specific logic but across all sessions
                        pass
                        
                except Exception as e:
                    continue
        
        # Format for frontend
        results = []
        for domain, stats in domain_stats.items():
            percentage = (stats['total_citations'] / total_brand_citations * 100) if total_brand_citations > 0 else 0
            results.append({
                'domain': domain,
                'count': stats['total_citations'],
                'percentage': round(percentage, 1),
                'urls': stats['urls'],
                'llms': list(stats['llms']),
                'competitors': list(stats['competitors']), 
                'type': 'Other', # Could be refined by domain lookups if needed
                'date': stats['first_seen']
            })
            
        # Sort by count desc
        results.sort(key=lambda x: x['count'], reverse=True)
        
        logger.info(f"✅ Aggregated {total_brand_citations} citations for brand '{brand_name}' spanning {len(session_ids)} sessions")
        return {'citations': results, 'total_citations': total_brand_citations}

    except Exception as e:
        logger.error(f"Error getting brand citation repository for {brand_name}: {e}")
        return {'citations': [], 'total_citations': 0}

def get_previous_sov_data(brand_name: str, user_id: str, current_session_id: str) -> List[Dict[str, Any]]:
    """
    Finds the most recent session before current_session_id and returns its SOV data.
    """
    try:
        # 1. Get current session timestamp
        current_session = supabase.table('analysis_sessions').select('timestamp').eq('session_id', current_session_id).execute()
        if not current_session.data:
            return []
        
        current_timestamp = current_session.data[0]['timestamp']

        # 2. Find the session immediately preceding this one for the same brand/user
        prev_session_query = supabase.table('analysis_sessions').select('session_id').eq('brand_name', brand_name).eq('user_id', user_id).lt('timestamp', current_timestamp).order('timestamp', desc=True).limit(1).execute()
        
        if not prev_session_query.data:
            return []
        
        prev_session_id = prev_session_query.data[0]['session_id']
        logger.info(f"Found previous session {prev_session_id} for comparison with {current_session_id}")

        # 3. Get SOV data for that previous session
        sov_response = supabase.table('share_of_voice').select('*').eq('session_id', prev_session_id).execute()
        return sov_response.data or []

    except Exception as e:
        logger.error(f"Error getting previous SOV data: {e}")
        return []


# ============================================================
# SCHEDULER FUNCTIONS
# ============================================================

# Allowed update_frequency values (frontend + backend must agree)
VALID_FREQUENCIES = {'1h', '6h', '12h', '24h', '48h', '7d', '14d', '30d'}

def claim_due_projects(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Claims projects that are due for a scheduled run directly via Supabase.

    A project is "due" when:
      - is_active = TRUE
      - sync_status is NOT 'running', OR sync_started_at is older than 30 min (self-heal stale runs)
      - last_sync_at is NULL (never synced) OR older than the project's update_frequency interval
    """
    try:
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        intervals = {
            '1h': timedelta(hours=1),
            '6h': timedelta(hours=6),
            '12h': timedelta(hours=12),
            '24h': timedelta(hours=24),
            '48h': timedelta(hours=48),
            '7d': timedelta(days=7),
            '14d': timedelta(days=14),
            '30d': timedelta(days=30),
        }

        # 1. Fetch active candidate projects from Supabase
        res = supabase.table('projects').select('*').eq('is_active', True).execute()
        candidates = res.data or []

        due_projects = []
        for p in candidates:
            sync_status = p.get('sync_status') or 'idle'
            sync_started_str = p.get('sync_started_at')

            # If running and not stale (>30m), skip
            if sync_status == 'running' and sync_started_str:
                try:
                    started_dt = datetime.fromisoformat(sync_started_str.replace('Z', '+00:00'))
                    if now - started_dt < timedelta(minutes=30):
                        continue
                except Exception:
                    pass

            last_sync_str = p.get('last_sync_at')
            if not last_sync_str:
                due_projects.append(p)
                continue

            try:
                last_sync_dt = datetime.fromisoformat(last_sync_str.replace('Z', '+00:00'))
                freq = p.get('update_frequency', '24h')
                delta = intervals.get(freq, timedelta(hours=24))
                if now - last_sync_dt >= delta:
                    due_projects.append(p)
            except Exception:
                due_projects.append(p)

        # 2. Claim up to `limit` projects
        batch = due_projects[:limit]
        claimed = []
        for p in batch:
            try:
                up_res = supabase.table('projects').update({
                    'sync_status': 'running',
                    'sync_started_at': now.isoformat(),
                    'updated_at': now.isoformat()
                }).eq('id', p['id']).execute()

                if up_res.data:
                    claimed.append(up_res.data[0])
                else:
                    p['sync_status'] = 'running'
                    p['sync_started_at'] = now.isoformat()
                    claimed.append(p)
            except Exception as e:
                logger.error(f"Error locking project {p.get('id')}: {e}")

        logger.info(f"Scheduler claimed {len(claimed)} project(s) via Supabase")
        return claimed

    except Exception as e:
        logger.error(f"Error claiming due projects: {e}", exc_info=True)
        return []


def release_project_lock(project_id: str, success: bool = True) -> bool:
    """
    Releases the scheduler lock on a project after a run via Supabase.
    - success=True  -> sync_status='idle', last_sync_at=NOW()
    - success=False -> sync_status='idle', last_sync_at unchanged (will retry next tick)
    """
    try:
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        update_data: Dict[str, Any] = {
            'sync_status': 'idle',
            'sync_started_at': None,
            'updated_at': now_iso,
        }
        if success:
            update_data['last_sync_at'] = now_iso

        supabase.table('projects').update(update_data).eq('id', project_id).execute()
        logger.info(f"Released lock on project {project_id} via Supabase (success={success})")
        return True
    except Exception as e:
        logger.error(f"Error releasing project lock {project_id}: {e}")
        return False


def record_daily_metrics(session_id: str) -> Dict[str, Any]:
    """
    Idempotent day-level metric aggregation using Supabase.
    Aggregates scoring results for the completed session grouped by LLM
    and updates daily_brand_metrics.
    """
    try:
        # 1. Fetch session metadata
        session_res = supabase.table('analysis_sessions').select('*').eq('session_id', session_id).execute()
        if not session_res.data:
            logger.warning(f"record_daily_metrics: Session {session_id} not found")
            return {'error': 'Session not found'}

        session_obj = session_res.data[0]
        project_id = session_obj.get('project_id')
        brand_name = session_obj.get('brand_name', 'Unknown')
        status = session_obj.get('status')

        if not project_id:
            logger.info(f"Session {session_id} is not linked to a project – skipping daily metrics")
            return {'skipped': True, 'reason': 'no_project_id'}

        # 2. Fetch scoring results for this session
        scores_res = supabase.table('scoring_results').select('*').eq('session_id', session_id).execute()
        scores_rows = scores_res.data or []

        if not scores_rows:
            logger.info(f"No scoring_results found for session {session_id}")
            return {'rows_upserted': 0}

        # 3. Group by LLM and aggregate
        from datetime import date
        today_iso = date.today().isoformat()

        llm_groups: Dict[str, List[Dict[str, Any]]] = {}
        for r in scores_rows:
            llm = r.get('llm_name') or 'unknown'
            llm_groups.setdefault(llm, []).append(r)

        upsert_rows = []
        for llm_name, rows in llm_groups.items():
            vis_scores = [
                float(r.get('normalized_visibility') or r.get('total_score') or 0)
                for r in rows
            ]
            avg_vis = sum(vis_scores) / len(vis_scores) if vis_scores else 0.0

            pos_values = [
                float(r.get('average_positioning') or r.get('brand_position'))
                for r in rows
                if (r.get('average_positioning') or r.get('brand_position')) is not None
            ]
            avg_pos = sum(pos_values) / len(pos_values) if pos_values else None

            mentions = sum(1 for r in rows if (r.get('brand_mention_score') or 0) > 0)

            # Column names match the actual daily_brand_metrics schema:
            # visibility_score, avg_position, mention_count, total_prompts, citation_count, date
            upsert_rows.append({
                'project_id': project_id,
                'llm_name': llm_name,
                'date': today_iso,
                'visibility_score': round(avg_vis, 2),
                'mention_count': mentions,
                'avg_position': round(avg_pos, 2) if avg_pos is not None else None,
                'total_prompts': len(rows),
            })

        # 4. Upsert into daily_brand_metrics via Supabase
        try:
            supabase.table('daily_brand_metrics').upsert(upsert_rows, on_conflict='project_id,llm_name,date').execute()
            logger.info(f"record_daily_metrics: successfully upserted {len(upsert_rows)} metric rows for project {project_id}")
            return {'rows_upserted': len(upsert_rows), 'date': today_iso, 'project_id': project_id}
        except Exception as up_err:
            logger.warning(f"Could not upsert daily_brand_metrics: {up_err}")
            return {'error': str(up_err), 'rows_attempted': len(upsert_rows)}

    except Exception as e:
        logger.error(f"Error in record_daily_metrics for session {session_id}: {e}", exc_info=True)
        return {'error': str(e)}

# ==============================================================================
# ADMIN PANEL DATABASE HELPERS
# ==============================================================================

def admin_list_users(
    search: Optional[str] = None,
    plan: Optional[str] = None,
    role: Optional[str] = None,
    is_suspended: Optional[bool] = None,
    page: int = 1,
    limit: int = 20
) -> Dict[str, Any]:
    """List users with pagination, search, and filters (Admin only)."""
    try:
        query = supabase.table('users').select(
            'id, email, role, is_suspended, subscription_plan, subscription_status, subscription_start, subscription_end, billing_cycle, credits_remaining, created_at',
            count='exact'
        )

        if search:
            query = query.ilike('email', f'%{search.strip()}%')
        if plan:
            query = query.eq('subscription_plan', plan.strip())
        if role:
            query = query.eq('role', role.strip())
        if is_suspended is not None:
            query = query.eq('is_suspended', is_suspended)

        start = max(0, (page - 1) * limit)
        end = start + limit - 1
        response = query.order('created_at', desc=True).range(start, end).execute()

        return {
            "users": response.data or [],
            "total": response.count or 0,
            "page": page,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Error in admin_list_users: {e}", exc_info=True)
        return {"users": [], "total": 0, "page": page, "limit": limit, "error": str(e)}


def admin_get_user_detail(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve full details of a user for the admin portal."""
    try:
        user_res = supabase.table('users').select(
            'id, email, role, is_suspended, credits_remaining, credits_total, created_at, updated_at, subscription_plan, subscription_status, subscription_start, subscription_end, billing_cycle, razorpay_payment_id'
        ).eq('id', user_id).execute()

        if not user_res.data:
            return None

        user = user_res.data[0]

        # Fetch user's recent sessions count and project count
        sessions_res = supabase.table('analysis_sessions').select('session_id', count='exact').eq('user_id', user_id).execute()
        projects_res = supabase.table('projects').select('id', count='exact').eq('user_id', user_id).execute()
        payments_res = supabase.table('payment_transactions').select('*').eq('user_id', user_id).order('created_at', desc=True).limit(5).execute()

        user["total_sessions"] = sessions_res.count or 0
        user["total_projects"] = projects_res.count or 0
        user["recent_payments"] = payments_res.data or []

        return user
    except Exception as e:
        logger.error(f"Error in admin_get_user_detail for {user_id}: {e}", exc_info=True)
        return None


def admin_update_user(user_id: str, fields: Dict[str, Any]) -> bool:
    """Update user fields (e.g. role, is_suspended, plan, credits) via admin."""
    try:
        from datetime import datetime, timezone
        fields["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = supabase.table('users').update(fields).eq('id', user_id).execute()
        return bool(res.data)
    except Exception as e:
        logger.error(f"Error in admin_update_user for {user_id}: {e}", exc_info=True)
        return False


def admin_list_payments(
    search: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20
) -> Dict[str, Any]:
    """List payment transactions with pagination and search."""
    try:
        query = supabase.table('payment_transactions').select('*', count='exact')

        if search:
            search_str = search.strip()
            query = query.or_(f"user_email.ilike.%{search_str}%,razorpay_payment_id.ilike.%{search_str}%,razorpay_order_id.ilike.%{search_str}%")
        if status:
            query = query.eq('status', status.strip())

        start = max(0, (page - 1) * limit)
        end = start + limit - 1
        response = query.order('created_at', desc=True).range(start, end).execute()

        return {
            "payments": response.data or [],
            "total": response.count or 0,
            "page": page,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Error in admin_list_payments: {e}", exc_info=True)
        return {"payments": [], "total": 0, "page": page, "limit": limit, "error": str(e)}


def admin_update_payment(payment_id: str, fields: Dict[str, Any]) -> bool:
    """Update payment transaction fields (e.g. status='refunded', refund_id)."""
    try:
        res = supabase.table('payment_transactions').update(fields).eq('razorpay_payment_id', payment_id).execute()
        return bool(res.data)
    except Exception as e:
        logger.error(f"Error in admin_update_payment for {payment_id}: {e}", exc_info=True)
        return False


def admin_get_stats() -> Dict[str, Any]:
    """Calculate high-level KPIs for the Admin Overview dashboard."""
    try:
        total_users_res = supabase.table('users').select('id', count='exact').execute()
        total_users = total_users_res.count or 0

        paid_users_res = supabase.table('users').select('id', count='exact').eq('subscription_status', 'active').neq('subscription_plan', 'free').execute()
        active_paid_users = paid_users_res.count or 0

        suspended_res = supabase.table('users').select('id', count='exact').eq('is_suspended', True).execute()
        suspended_users = suspended_res.count or 0

        sessions_res = supabase.table('analysis_sessions').select('session_id', count='exact').execute()
        total_sessions = sessions_res.count or 0

        projects_res = supabase.table('projects').select('id', count='exact').execute()
        total_projects = projects_res.count or 0

        # Plan breakdown
        users_by_plan: Dict[str, int] = {}
        all_plans_res = supabase.table('users').select('subscription_plan').execute()
        for r in (all_plans_res.data or []):
            plan_name = (r.get('subscription_plan') or 'free').lower()
            users_by_plan[plan_name] = users_by_plan.get(plan_name, 0) + 1

        # Recent 5 audit logs
        recent_audits = supabase.table('admin_audit_logs').select('*').order('created_at', desc=True).limit(5).execute()

        # Total estimated LLM cost from usage_logs (if table exists)
        total_cost = 0.0
        try:
            cost_res = supabase.table('usage_logs').select('est_cost_usd').execute()
            total_cost = sum(float(row.get('est_cost_usd') or 0) for row in (cost_res.data or []))
        except Exception:
            pass

        return {
            "total_users": total_users,
            "active_paid_users": active_paid_users,
            "suspended_users": suspended_users,
            "total_sessions": total_sessions,
            "total_projects": total_projects,
            "users_by_plan": users_by_plan,
            "total_est_cost_usd": round(total_cost, 4),
            "recent_audits": recent_audits.data or []
        }
    except Exception as e:
        logger.error(f"Error in admin_get_stats: {e}", exc_info=True)
        return {
            "total_users": 0,
            "active_paid_users": 0,
            "suspended_users": 0,
            "total_sessions": 0,
            "total_projects": 0,
            "users_by_plan": {},
            "total_est_cost_usd": 0.0,
            "recent_audits": [],
            "error": str(e)
        }


def admin_list_audit_logs(
    action: Optional[str] = None,
    target_type: Optional[str] = None,
    page: int = 1,
    limit: int = 20
) -> Dict[str, Any]:
    """List admin audit logs with pagination and filters."""
    try:
        query = supabase.table('admin_audit_logs').select('*', count='exact')
        if action:
            query = query.eq('action', action.strip())
        if target_type:
            query = query.eq('target_type', target_type.strip())

        start = max(0, (page - 1) * limit)
        end = start + limit - 1
        response = query.order('created_at', desc=True).range(start, end).execute()

        return {
            "logs": response.data or [],
            "total": response.count or 0,
            "page": page,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Error in admin_list_audit_logs: {e}", exc_info=True)
        return {"logs": [], "total": 0, "page": page, "limit": limit, "error": str(e)}


def admin_list_usage_logs(
    user_id: Optional[str] = None,
    activity_type: Optional[str] = None,
    page: int = 1,
    limit: int = 20
) -> Dict[str, Any]:
    """List usage logs with pagination and filters."""
    try:
        query = supabase.table('usage_logs').select('*', count='exact')
        if user_id:
            query = query.eq('user_id', user_id.strip())
        if activity_type:
            query = query.eq('activity_type', activity_type.strip())

        start = max(0, (page - 1) * limit)
        end = start + limit - 1
        response = query.order('created_at', desc=True).range(start, end).execute()

        return {
            "logs": response.data or [],
            "total": response.count or 0,
            "page": page,
            "limit": limit
        }
    except Exception as e:
        logger.error(f"Error in admin_list_usage_logs: {e}", exc_info=True)
        return {"logs": [], "total": 0, "page": page, "limit": limit, "error": str(e)}


# ─── PLANS CMS & PRICING ENGINE ───────────────────────────────────────────────
import time

# Lightweight in-memory TTL cache (60s staleness window)
_PLANS_CACHE: Dict[str, Any] = {
    "data": None,
    "timestamp": 0.0,
    "ttl": 60.0
}


def invalidate_plans_cache():
    """Invalidates the in-memory plans cache immediately upon CMS writes."""
    _PLANS_CACHE["timestamp"] = 0.0
    _PLANS_CACHE["data"] = None


def alert_db_fallback(context: str, error: Any):
    """Critical alert when backend is forced to fall back to hardcoded plan dicts."""
    logger.critical(f"🚨 [CRITICAL_DB_FALLBACK] {context}: Database failed ({error}). Reverting to hardcoded plan constants.")
    alert_webhook = os.getenv("ALERT_WEBHOOK_URL")
    if alert_webhook:
        try:
            import urllib.request
            import json
            req = urllib.request.Request(
                alert_webhook,
                data=json.dumps({"text": f"🚨 [CRITICAL_DB_FALLBACK] {context}: {error}"}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception as alert_ex:
            logger.error(f"Failed to deliver fallback alert to webhook: {alert_ex}")


def canonicalize_plan_name(name: Optional[str]) -> str:
    """Normalizes any incoming plan identifier to the canonical single-word plan name."""
    if not name:
        return "free"
    cleaned = name.lower().strip()
    if cleaned in ("lite plan", "lite", "starter"):
        return "lite"
    if cleaned in ("growth plan", "growth"):
        return "growth"
    if cleaned in ("pro plan", "pro", "professional"):
        return "pro"
    if cleaned in ("enterprise", "custom", "custom plan"):
        return "enterprise"
    if cleaned in ("free", "basic"):
        return "free"
    return cleaned


def get_all_plans(active_only: bool = False) -> List[Dict[str, Any]]:
    """
    Returns plans sorted by sort_order.
    Caches active plans for 60 seconds to relieve database load.
    """
    now = time.monotonic()
    if active_only and _PLANS_CACHE["data"] and (now - _PLANS_CACHE["timestamp"] < _PLANS_CACHE["ttl"]):
        return _PLANS_CACHE["data"]

    try:
        query = supabase.table('plans').select('*').order('sort_order', desc=False)
        if active_only:
            query = query.eq('is_active', True)
        res = query.execute()
        plans = res.data or []

        if active_only and plans:
            _PLANS_CACHE["data"] = plans
            _PLANS_CACHE["timestamp"] = now

        return plans
    except Exception as e:
        alert_db_fallback("get_all_plans", e)
        return []


def get_plan_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Fetches a single plan by its canonical name. Respects the 60s TTL cache."""
    canon = canonicalize_plan_name(name)
    # Check cache first — only serve if within TTL
    now = time.monotonic()
    cached = _PLANS_CACHE.get("data")
    if cached and (now - _PLANS_CACHE["timestamp"] < _PLANS_CACHE["ttl"]):
        for p in cached:
            if p.get("name") == canon:
                return p

    try:
        res = supabase.table('plans').select('*').eq('name', canon).limit(1).execute()
        if res.data and len(res.data) > 0:
            return res.data[0]
        return None
    except Exception as e:
        alert_db_fallback(f"get_plan_by_name({canon})", e)
        return None


def get_plan_by_id(plan_id: str) -> Optional[Dict[str, Any]]:
    """Fetches a single plan by its UUID."""
    try:
        res = supabase.table('plans').select('*').eq('id', plan_id).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"Error in get_plan_by_id: {e}")
        return None


def create_plan(plan_data: Dict[str, Any]) -> Dict[str, Any]:
    """Creates a new plan in the database with version 1."""
    try:
        plan_data["name"] = canonicalize_plan_name(plan_data.get("name"))
        plan_data["version"] = 1
        plan_data["currency"] = plan_data.get("currency", "INR")
        res = supabase.table('plans').insert(plan_data).execute()
        invalidate_plans_cache()
        if not res.data:
            raise Exception("Failed to insert plan into Supabase")
        return res.data[0]
    except Exception as e:
        logger.error(f"Error in create_plan: {e}")
        raise


def update_plan(
    plan_id: str,
    fields: Dict[str, Any],
    expected_version: Optional[int] = None,
    admin_user_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Updates an existing plan with optimistic locking and price version auditing.
    Raises HTTPException(409) if version conflict occurs.
    """
    current = get_plan_by_id(plan_id)
    if not current:
        raise HTTPException(status_code=404, detail="Plan not found")

    current_version = current.get("version", 1)
    if expected_version is not None and current_version != expected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Conflict: Plan was modified by another administrator (expected v{expected_version}, current v{current_version}). Please refresh."
        )

    # Calculate field diff
    diff = {}
    for k, v in fields.items():
        if k in current and current[k] != v:
            diff[k] = {"old": current[k], "new": v}

    # Price history audit: if price changed, record historical snapshot
    monthly_changed = "monthly_price_paise" in fields and fields["monthly_price_paise"] != current.get("monthly_price_paise")
    yearly_changed = "yearly_price_paise" in fields and fields["yearly_price_paise"] != current.get("yearly_price_paise")
    if monthly_changed or yearly_changed:
        try:
            supabase.table('plan_price_history').insert({
                "plan_id": plan_id,
                "monthly_price_paise": fields.get("monthly_price_paise", current.get("monthly_price_paise", 0)),
                "yearly_price_paise": fields.get("yearly_price_paise", current.get("yearly_price_paise", 0)),
                "currency": fields.get("currency", current.get("currency", "INR")),
                "changed_by": admin_user_id,
                "change_reason": fields.get("change_reason", "CMS price update")
            }).execute()
        except Exception as hist_err:
            logger.warning(f"Could not record plan_price_history: {hist_err}")

    # Increment version and update
    fields["version"] = current_version + 1
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    # Don't persist change_reason on plans table
    fields.pop("change_reason", None)

    try:
        res = supabase.table('plans').update(fields).eq('id', plan_id).eq('version', current_version).execute()
        if not res.data:
            raise HTTPException(status_code=409, detail="Conflict: Plan was updated concurrently. Please refresh.")

        invalidate_plans_cache()
        return {"updated_plan": res.data[0], "diff": diff, "old_plan": current}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_plan: {e}")
        raise



"""
Prospecting Orchestrator v2: Enhanced with Company Search Integration
Coordinates all sub-agents in the prospecting workflow with intelligent prompt routing.
"""

import asyncio
import uuid
import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional, List
import os
import time
import signal
import atexit

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.sub_agents.web_research_agent import WebResearchAgent
from app.agents.sub_agents.youtube_media_agent import YouTubeMediaAgent
from app.utils.langsmith_config import trace_operation, create_main_run, initialize_langsmith
from app.agents.sub_agents.coresignal_agent import CoreSignalSubAgent
from app.agents.sub_agents.company_enrich_agent import CompanyEnrichAgent
from app.agents.sub_agents.person_enrich_agent import PersonEnrichAgent
from app.agents.sub_agents.company_search_agent import CompanySearchAgent
from app.agents.sub_agents.ria_detection_agent import RIADetectionAgent
from app.utils.domain_utils import generate_company_id_from_domain
from app.tools.search_module import find_company_homepage_url_perplexity
from app.utils.global_db import get_global_db
from app.utils.db_utils import ProspectingDB
from app.prompts.data_process_prompts import get_prompt_analysis_system_prompt
from app.utils.logging_config import get_logger
from app.utils.config import get_openai_api_key, get_enable_postgres_storage, get_enable_debugging
from app.utils.progress_store import ProgressStore
from app.utils.rate_limit import RateLimiter

logger = get_logger(__name__)

# Session context data structure
class SessionContext:
    """Session context for managing user interactions within a session."""
    
    def __init__(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.start_time = datetime.now()
        self.interaction_count = 0
        self.status = "active"
        self.last_activity = datetime.now()
        self.ria_detection_result: Optional[Dict[str, Any]] = None
    
    def increment_interaction(self) -> str:
        """Increment interaction counter and return run_id for this interaction."""
        self.interaction_count += 1
        self.last_activity = datetime.now()
        return f"{self.session_id}_{self.interaction_count:03d}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert session context to dictionary for storage."""
        return {
            'session_id': self.session_id,
            'user_id': self.user_id,
            'start_time': self.start_time.isoformat(),
            'interaction_count': self.interaction_count,
            'status': self.status,
            'last_activity': self.last_activity.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionContext':
        """Create session context from dictionary."""
        session = cls(data['session_id'], data['user_id'])
        session.start_time = datetime.fromisoformat(data['start_time'])
        session.interaction_count = data['interaction_count']
        session.status = data['status']
        session.last_activity = datetime.fromisoformat(data['last_activity'])
        return session

class PromptAnalyzer:
    """
    Analyzes user prompts to determine if they contain specific company names or general search requests.
    """
    
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, api_key=get_openai_api_key())
        
    async def analyze_prompt(self, prompt: str) -> Dict[str, Any]:
        """
        Analyze a user prompt to determine the type of request using LLM.
        
        Args:  
            prompt: User's input prompt
            
        Returns:
            Dictionary with analysis results:
            - prompt_type: "specific_company", "general_search", or "off_topic"
            - confidence: Confidence score (0-1)
            - extracted_data: Relevant extracted information
        """
        logger.info("Prompt analysis initiated", extra={"prompt_length": len(prompt)})
        try:
            result = await self._llm_based_classification(prompt)
            logger.info("Prompt analysis completed", extra={"prompt_type": result.get("prompt_type"), "confidence": result.get("confidence", 0.0)})
            return result
            
        except Exception as e:
            logger.exception("Prompt analysis failed")
            print(f"⚠️ Prompt analysis failed: {e}")
            # Fallback to off_topic classification
            return {
                'prompt_type': 'off_topic',
                'confidence': 0.0,
                'extracted_data': {}
            }
    
    async def _llm_based_classification(self, prompt: str) -> Dict[str, Any]:
        """
        Use LLM to classify the prompt into one of four categories.
        """
        system_prompt = get_prompt_analysis_system_prompt()
        user_prompt = f"Analyze this prompt: {prompt}"
        
        try:
            with trace_operation("prompt_analysis", {
                "prompt_length": len(prompt),
                "model": "gpt-4o-mini"
            }):
                messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
                response = await self.llm.ainvoke(messages)
            
            # Parse JSON response
            response_text = response.content.strip()
            if '```json' in response_text:
                json_start = response_text.find('```json') + 7
                json_end = response_text.find('```', json_start)
                response_text = response_text[json_start:json_end].strip()
            
            result = json.loads(response_text)
            
            # Add off_topic message if needed
            if result['prompt_type'] == 'off_topic':
                result['extracted_data']['message'] = "I can help you with company research in two ways:\n\n1. **Specific Company Research**: Provide a company name and I'll research and enrich that specific company (e.g., 'Research Sequoia Capital' or 'Tell me about BlackRock')\n\n2. **General Company Search**: Search for companies matching specific criteria (e.g., 'Find VC firms in London focusing on fintech' or 'Show me private equity firms in healthcare')\n\nPlease provide either a specific company name to research or search criteria for finding companies."
            
            return result
            
        except Exception as e:
            print(f"⚠️ LLM classification failed: {e}")
            return {
                'prompt_type': 'off_topic',
                'confidence': 0.0,
                'extracted_data': {
                    'message': "I can help you with company research in two ways:\n\n1. **Specific Company Research**: Provide a company name and I'll research and enrich that specific company (e.g., 'Research Sequoia Capital' or 'Tell me about BlackRock')\n\n2. **General Company Search**: Search for companies matching specific criteria (e.g., 'Find VC firms in London focusing on fintech' or 'Show me private equity firms in healthcare')\n\nPlease provide either a specific company name to research or search criteria for finding companies."
                }
            }


class ProspectingOrchestrator:
    """
    Enhanced prospecting orchestrator that coordinates multiple sub-agents for comprehensive company research.
    
    This orchestrator provides three main execution modes:
    1. execute_from_prompt(): Process natural language user prompts
    2. execute_from_data(): Process structured company data
    3. execute_hybrid(): Automatically choose the best approach
    
    Features:
    - Intelligent prompt analysis and classification
    - Multi-agent coordination with error handling
    - Comprehensive data fusion and storage
    - Interactive mode for testing
    - MCP tool integration for enhanced capabilities
    """
    
    def __init__(self, db=None, extractor_llm=None, output_dir="output/prospecting", enable_debugging: Optional[bool] = None):
        """
        Initialize the prospecting orchestrator with sub-agents and configuration.
        
        Args:
            db: Optional database instance (will use global if not provided)
            extractor_llm: LangChain LLM instance for data extraction
            output_dir: Directory for storing output files
            enable_debugging: Whether to create debugging output files
        """
        # Initialize LangSmith first
        initialize_langsmith()
        
        # Resolve debugging flag from env if not explicitly provided
        resolved_enable_debugging = get_enable_debugging() if enable_debugging is None else enable_debugging

        # Only honor custom output_dir when debugging is enabled; otherwise use current dir
        effective_output_dir = output_dir if resolved_enable_debugging else "."
        self.output_dir = effective_output_dir
        self.extractor_llm = extractor_llm
        self.enable_debugging = resolved_enable_debugging
        
        # Always use None for database - sub-agents will get global instance
        self.db = None
        print("🔗 ProspectingOrchestrator: Initialized to use global database instance")
        
        # Initialize MCP tools first
        self.mcp_tools = {}
        
        # Initialize sub-agents without database - they will get global instance
        self.sub_agents = {
            'company_search': CompanySearchAgent(output_dir=effective_output_dir, db=None),
            'coresignal': CoreSignalSubAgent(output_dir=effective_output_dir, mcp_tools=self.mcp_tools, db=None),
            'web_research': WebResearchAgent(output_dir=effective_output_dir, mcp_tools=self.mcp_tools, db=None),
            'person_enrich': PersonEnrichAgent(output_dir=effective_output_dir, num_people=2, db=None),
            'company_enrich': CompanyEnrichAgent(output_dir=effective_output_dir, db=None),
            'youtube_media': YouTubeMediaAgent(output_dir=effective_output_dir, db=None)
        }
        
        # Initialize prompt analyzer
        self.prompt_analyzer = PromptAnalyzer()
        
        # Session management
        self.active_sessions: Dict[str, SessionContext] = {}
        self.session_timeout_hours = 24  # Default session timeout
        
        # Register cleanup handlers
        atexit.register(self._cleanup_all_sessions)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        debug_status = "with debugging enabled" if self.enable_debugging else "without debugging"
        print(f"✅ ProspectingOrchestrator initialized {debug_status}")
        logger.info("ProspectingOrchestrator initialized", extra={"output_dir": output_dir, "enable_debugging": self.enable_debugging, "sub_agents_count": len(self.sub_agents)})

    def _signal_handler(self, signum, frame):
        """Handle termination signals to ensure session cleanup."""
        print(f"\n🛑 Received signal {signum}, cleaning up sessions...")
        self._cleanup_all_sessions()
        exit(0)
    
    async def start_session(self, user_id: str = None) -> SessionContext:
        """
        Start a new session for a user.
        
        Args:
            user_id: User identifier (generated if not provided)
            
        Returns:
            SessionContext object with session details
        """
        if not user_id:
            user_id = f"user_{uuid.uuid4().hex[:8]}"
            
        session_id = f"session_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()
        
        session_context = SessionContext(
            session_id=session_id,
            user_id=user_id
        )
        
        # Always get global database instance
        self.db = await get_global_db()
        print(f"🔗 ProspectingOrchestrator: Using global database instance: {id(self.db)}")
        
        # Store session in database
        session_data = {
            'session_id': session_id,
            'user_id': user_id,
            'start_time': start_time,
            'last_activity': start_time,
            'interaction_count': 0,
            'status': 'active'
        }
        
        await self.db.store_session(session_data)
        
        print(f"🚀 Started new session: {session_id}")
        print(f"👤 User ID: {user_id}")
        print(f"⏰ Start time: {start_time}")
        
        logger.info("Session started", extra={"session_id": session_id, "user_id": user_id, "start_time": start_time.isoformat()})
        
        return session_context
    
    async def end_session(self, session_context: SessionContext) -> None:
        """
        End the current session.
        
        Args:
            session_context: Session context to end
        """
        if not session_context:
            return
            
        end_time = datetime.now()
        session_context.status = "ended"
        
        # Always get global database instance
        self.db = await get_global_db()
        
        # Update session in database
        await self.db.update_session_status(
            session_context.session_id, 
            "ended", 
            end_time
        )
        
        print(f"🏁 Ended session: {session_context.session_id}")
        print(f"📊 Total interactions: {session_context.interaction_count}")
        print(f"⏰ End time: {end_time}")
        
        logger.info("Session ended", extra={"session_id": session_context.session_id, "user_id": session_context.user_id, "interaction_count": session_context.interaction_count, "end_time": end_time.isoformat()})
    
    async def store_session_interaction(self, session_context: SessionContext, run_id: str, prompt: str, workflow_type: str) -> None:
        """
        Store a session interaction in the database.
        
        Args:
            session_context: Current session context
            run_id: Unique run identifier
            prompt: User prompt
            workflow_type: Type of workflow executed
        """
        if not session_context:
            return
            
        # Always get global database instance
        self.db = await get_global_db()
            
        interaction_id = f"interaction_{uuid.uuid4().hex[:12]}"
        start_time = datetime.now()
        
        interaction_data = {
            'interaction_id': interaction_id,
            'session_id': session_context.session_id,
            'run_id': run_id,
            'interaction_number': session_context.interaction_count,
            'prompt': prompt,
            'workflow_type': workflow_type,
            'start_time': start_time
        }
        
        await self.db.store_session_interaction(interaction_data)
        
        # Update session interaction count and last activity
        session_context.interaction_count += 1
        session_context.last_activity = start_time
        
        session_data = {
            'session_id': session_context.session_id,
            'user_id': session_context.user_id,
            'start_time': session_context.start_time,
            'last_activity': start_time,
            'interaction_count': session_context.interaction_count,
            'status': session_context.status
        }
        
        await self.db.store_session(session_data)
        
        logger.info("Session interaction stored", extra={"session_id": session_context.session_id, "run_id": run_id, "workflow_type": workflow_type, "interaction_number": session_context.interaction_count})

    def _cleanup_all_sessions(self):
        """Clean up all active sessions (called on exit)."""
        if self.active_sessions:
            print(f"🧹 Cleaning up {len(self.active_sessions)} active sessions...")
            for session_id in list(self.active_sessions.keys()):
                try:
                    # Use asyncio.run if we're not already in an async context
                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        # We're in an async context, create a task
                        loop.create_task(self.end_session(self.active_sessions[session_id]))
                    except RuntimeError:
                        # No running loop, create a new one
                        asyncio.run(self.end_session(self.active_sessions[session_id]))
                except Exception as e:
                    print(f"⚠️ Failed to cleanup session {session_id}: {e}")
    
    async def cleanup_expired_sessions(self) -> int:
        """
        Clean up expired sessions based on timeout.
        
        Returns:
            Number of sessions cleaned up
        """
        cleaned_count = 0
        timeout_threshold = datetime.now() - timedelta(hours=self.session_timeout_hours)
        
        for session_id, session_context in list(self.active_sessions.items()):
            if session_context.last_activity < timeout_threshold:
                await self.end_session(session_context)
                cleaned_count += 1
        
        if cleaned_count > 0:
            print(f"🧹 Cleaned up {cleaned_count} expired sessions")
        
        return cleaned_count

    async def execute(self, prompt: str, user_id: str, session_context: SessionContext, run_id: str | None = None) -> Dict[str, Any]:
        """
        Execute the prospecting orchestrator with session-aware run_id generation.
        
        Args:
            prompt: User's input prompt
            user_id: User identifier for multi-tenant isolation
            session_context: Session context for session-aware execution
            
        Returns:
            Dictionary with execution results including session information
        """
        start_time = datetime.now()
        
        # Always get global database instance
        self.db = await get_global_db()
        print(f"🔗 ProspectingOrchestrator.execute: Using global database instance: {id(self.db)}")
        
        # Use provided run_id from router if available; otherwise generate from session context
        if not run_id:
            run_id = f"{session_context.session_id}_run_{session_context.interaction_count + 1:03d}"
        output_file = f"prospecting_results_{session_context.session_id}_{session_context.interaction_count:03d}.json"
        
        print(f"🔄 Session: {session_context.session_id}")
        print(f"👤 User: {session_context.user_id}")
        print(f"📝 Interaction: {session_context.interaction_count}")
        print(f"🆔 Run ID: {run_id}")
        
        print(f"📄 Output file: {output_file}")
        print(f"💬 User prompt: {prompt}")
        
        logger.info("Orchestrator execution started", extra={"run_id": run_id, "user_id": user_id, "session_id": session_context.session_id, "prompt_length": len(prompt)})
        try:
            await ProgressStore.instance().set_progress(self.db, run_id, 10)
        except Exception:
            pass
        
        # Store session interaction if session context is provided
        await self.store_session_interaction(
            session_context, 
            run_id, 
            prompt, 
            "prospecting_orchestration"
        )
        
        # Ensure user_id is available
        if not user_id:
            user_id = session_context.user_id
        
        # Create shared output file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.enable_debugging:
            # Create debug file in output/prospecting directory
            debug_dir = "output/prospecting"
            os.makedirs(debug_dir, exist_ok=True)
            shared_output_file = f"{debug_dir}/debug_{timestamp}.md"
            print(f"🐛 Debug file created: {shared_output_file}")
        else:
            shared_output_file = None
        
        # Ensure output directory exists only when debugging output is enabled
        if self.enable_debugging:
            os.makedirs(self.output_dir, exist_ok=True)
        
        # Create main LangSmith run context
        run_metadata = {
            'prompt': prompt,
            'workflow_type': 'prospecting_orchestration',
            'session_id': session_context.session_id,
            'interaction_count': session_context.interaction_count
        }
        
        with create_main_run(run_id, user_id, session_context.session_id, run_metadata):
            try:
                # Retrieve and display user bio
                user_bio = None
                try:
                    user_bio = await self.db.get_user_profile(user_id)
                    if user_bio:
                        print(f"\n👤 User Profile for {user_id}:")
                        print("=" * 60)
                        print(f"🏢 Firm Description ({len(user_bio['firm_description'])} characters):")
                        print("-" * 40)
                        print(user_bio['firm_description'])
                        print(f"\n🎯 Key Differentiators ({len(user_bio['key_differentiators'])} characters):")
                        print("-" * 40)
                        print(user_bio['key_differentiators'])
                        print(f"\n🎯 Key Objectives ({len(user_bio['key_objectives'])} characters):")
                        print("-" * 40)
                        print(user_bio['key_objectives'])
                        print("=" * 60)
                    else:
                        print(f"ℹ️ No user profile found for user: {user_id}")
                except Exception as e:
                    print(f"⚠️ Error retrieving user profile: {e}")
                
                # Step 1: Analyze prompt and determine workflow
                print(f"🔍 Step 1: Analyzing user prompt"
                prompt_analysis = await self.prompt_analyzer.analyze_prompt(prompt)
                workflow_type = prompt_analysis['prompt_type']
                print(f"✅ Prompt analysis complete: {workflow_type} (confidence: {prompt_analysis['confidence']:.2f})")
                
                logger.info("Workflow routing", extra={"run_id": run_id, "workflow_type": workflow_type, "confidence": prompt_analysis.get("confidence", 0.0)})
                
                # Step 2: Route to appropriate workflow
                if workflow_type == 'specific_company':
                    return await self._execute_specific_company_workflow(
                        prompt_analysis['extracted_data'], run_id, user_id, shared_output_file, self.db, get_enable_postgres_storage(), session_context, workflow_type
                    )
                elif workflow_type == 'general_search':
                    return await self._execute_company_search_workflow(
                        prompt_analysis['extracted_data'], run_id, user_id, shared_output_file, self.db, get_enable_postgres_storage(), session_context, workflow_type
                    )
                elif workflow_type == 'off_topic':
                    return {
                        'success': True,
                        'workflow_type': 'off_topic',
                        'message': prompt_analysis['extracted_data'].get('message', 'Off-topic request'),
                        'prompt_analysis': prompt_analysis,
                        'run_id': run_id,
                        'user_id': user_id,
                        'session_id': session_context.session_id,
                        'interaction_number': session_context.interaction_count,
                        'execution_time_ms': int((datetime.now() - start_time).total_seconds() * 1000),
                        'next_step': 'wait_for_user_input'
                    }
                else:
                    # Fallback for any unexpected types
                    return {
                        'success': False,
                        'error': 'Unexpected prompt type - please provide a specific company name or clear search criteria',
                        'prompt_analysis': prompt_analysis,
                        'run_id': run_id,
                        'user_id': user_id,
                        'session_id': session_context.session_id,
                        'execution_time_ms': int((datetime.now() - start_time).total_seconds() * 1000)
                    }
                        
            except Exception as e:
                import traceback
                print(f"\n❌ [ProspectingOrchestrator ERROR] Exception in execute():\n{traceback.format_exc()}")
                
                execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                
                logger.exception("Orchestrator execution failed", extra={"run_id": run_id, "user_id": user_id, "session_id": session_context.session_id})
                
                return {
                    'success': False,
                    'error': str(e),
                    'run_id': run_id,
                    'user_id': user_id,
                    'session_id': session_context.session_id,
                    'execution_time_ms': execution_time_ms
                }
            finally:
                # Note: Database connection is managed globally, no need to close here
                pass

    async def _execute_specific_company_workflow(self, company_data: Dict[str, Any], run_id: str, user_id: str, 
                                               shared_output_file: str, db: ProspectingDB, postgres_enabled: bool, session_context: SessionContext, workflow_type: str) -> Dict[str, Any]:
        """
        Execute the traditional prospecting workflow for a specific company.
        """
        start_time = datetime.now()
        
        company_name = company_data.get('company_name', 'Unknown Company')
        logger.info("Specific company workflow started", extra={"run_id": run_id, "company_name": company_name, "workflow_type": workflow_type})
        
        print(f"🎯 Executing specific company workflow for: {company_data.get('company_name', 'Unknown')}")
        
        # Prepare company data for existing workflow
        company_name = company_data.get('company_name', 'Unknown Company')
        location = company_data.get('location')
        hq_city = company_data.get('hq_city')
        hq_country = company_data.get('hq_country')
        focus_area = company_data.get('focus_area')
        
        # Set up company_data like in original orchestrator
        company_data_for_workflow = {
            'name': company_name,
            'location': location or 'Unknown',
            'hq_city': hq_city,
            'hq_country': hq_country,
            'focus_area': focus_area or 'General prospecting',
            'output_file': shared_output_file
        }
        
        # Execute the original workflow steps
        try:
            # Step 1: Domain Discovery and Company ID Generation
            print(f"🔍 Step 1: Domain discovery for {company_name}")
            domain_discovery_result = await self._discover_domain_and_generate_id(company_data_for_workflow, shared_output_file)
            
            # Early exit if no valid domain found
            found_url = domain_discovery_result.get('found_url')
            if (not domain_discovery_result['success'] or 
                found_url is None or 
                (isinstance(found_url, str) and found_url.strip().lower() in ('null', '[null]', 'none', '')) or
                (isinstance(found_url, list) and (not found_url or found_url[0] in (None, 'null', '[null]', 'none', '')))):
                error_msg = "No valid company domain could be found. Sub-agents were not executed."
                print(f"❌ {error_msg}")
                logger.warning("Domain discovery failed", extra={"run_id": run_id, "company_name": company_name, "error": error_msg})
                try:
                    # Mark component states for FE polling stop logic
                    await ProgressStore.instance().update_component_status(self.db, run_id, "domain_resolution", "failed", "DOMAIN_NOT_FOUND", error_msg)
                    await ProgressStore.instance().update_component_status(self.db, run_id, "company_enrichment", "failed", "DOMAIN_NOT_FOUND", error_msg)
                except Exception:
                    pass
                return {
                    'success': False,
                    'error': error_msg,
                    'run_id': run_id,
                    'company_name': company_name,
                    'execution_time_ms': 0
                }
            
            company_id = domain_discovery_result['company_id']
            found_url = domain_discovery_result['found_url']
            found_by_perplexity = domain_discovery_result['found_by_perplexity']
            
            logger.info("Domain discovery completed", extra={"run_id": run_id, "company_id": company_id, "found_url": found_url, "found_by_perplexity": found_by_perplexity})
            
            # Start the prospecting run to ensure the run_id exists in the database
            if postgres_enabled and db:
                try:
                    await db.start_run(
                        run_id=run_id,
                        user_id=user_id,
                        session_id=session_context.session_id,
                        search_params=None,  # No search params for specific company
                        company_name=company_name,
                        company_id=company_id,
                        workflow_type=workflow_type
                    )
                    print(f"✅ Started prospecting run: {run_id}")
                except Exception as e:
                    print(f"⚠️ Warning: Failed to start prospecting run: {e}")
                    # Continue anyway - the workflow might still work
            
            # Store company in PostgreSQL if enabled
            if postgres_enabled and db:
                try:
                    company_data_for_db = {
                        'name': company_name,
                        'website_url': found_url,
                        'location': location,  # Keep for backward compatibility
                        'hq_city': hq_city,
                        'hq_country': hq_country,
                        'focus_area': focus_area
                    }
                    await db.store_company(
                        run_id=run_id,
                        company_data=company_data_for_db,
                        company_id=company_id,
                        user_id=user_id,
                        session_id=session_context.session_id
                    )
                    print(f"✅ Company stored in PostgreSQL with ID: {company_id}")
                except Exception as e:
                    print(f"⚠️ Error storing company in PostgreSQL: {e}")
            
            # Step 2: Phase 1 - Parallel Data Collection
            print(f"🔄 Step 2: Phase 1 - Parallel data collection")
            logger.info("Phase 1 data collection started", extra={"run_id": run_id, "company_id": company_id})
            phase1_result = await self._run_phase1_parallel(
                company_data_for_workflow, run_id, company_id, domain_discovery_result['found_url'], 
                domain_discovery_result['found_urls'], domain_discovery_result['found_by_perplexity'], 
                shared_output_file, user_id, session_id=session_context.session_id
            )
            
            if not phase1_result['success']:
                logger.error("Phase 1 data collection failed", extra={"run_id": run_id, "company_id": company_id, "error": phase1_result.get("error")})
                return {
                    'success': False,
                    'error': f"Phase 1 failed: {phase1_result['error']}",
                    'run_id': run_id,
                    'company_name': company_name,
                    'execution_time_ms': 0
                }
            
            logger.info("Phase 1 data collection completed", extra={"run_id": run_id, "company_id": company_id})
            
            # Step 3: Phase 2 - Parallel Enrichment
            print(f"🔄 Step 3: Phase 2 - Parallel enrichment")
            logger.info("Phase 2 enrichment started", extra={"run_id": run_id, "company_id": company_id})
            phase2_result = await self._run_phase2_parallel(
                company_data_for_workflow, run_id, company_id, shared_output_file, user_id, session_id=session_context.session_id, session_context=session_context
            )
            
            if not phase2_result['success']:
                logger.error("Phase 2 enrichment failed", extra={"run_id": run_id, "company_id": company_id, "error": phase2_result.get("error")})
                return {
                    'success': False,
                    'error': f"Phase 2 failed: {phase2_result['error']}",
                    'run_id': run_id,
                    'company_name': company_name,
                    'execution_time_ms': 0
                }
            
            logger.info("Phase 2 enrichment completed", extra={"run_id": run_id, "company_id": company_id})
            
            # Step 4: Generate Summary Report
            execution_time_ms = int((datetime.now() - datetime.now()).total_seconds() * 1000)  # Will be calculated properly
            
            summary_result = await self._generate_summary_report(
                company_data=company_data_for_workflow,
                run_id=run_id,
                company_id=company_id,
                phase1_result=phase1_result,
                phase2_result=phase2_result,
                execution_time_ms=execution_time_ms,
                shared_output_file=shared_output_file,
                session_context=session_context
            )
            
            print(f"✅ Specific company workflow completed successfully")
            
            # At the end of successful execution, before the return:
            # Note: Tally increment is handled in execute_workflow_background to avoid double-counting
            if postgres_enabled and db:
                execution_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                await db.complete_prospecting_run(run_id, user_id, session_context.session_id, execution_time_ms)
            
            logger.info("Specific company workflow completed successfully", extra={"run_id": run_id, "company_id": company_id, "execution_time_ms": execution_time_ms})
            
            return {
                'success': True,
                'workflow_type': workflow_type,
                'run_id': run_id,
                'company_id': company_id,
                'company_name': company_name,
                'execution_time_ms': execution_time_ms,
                'output_file': shared_output_file,
                'phase1_results': phase1_result,
                'phase2_results': phase2_result,
                'summary': summary_result,
                'postgres_enabled': postgres_enabled
            }
            
        except Exception as e:
            error_msg = f"Specific company workflow failed: {str(e)}"
            print(f"❌ {error_msg}")
            logger.exception("Specific company workflow failed", extra={"run_id": run_id, "company_name": company_name})
            return {
                'success': False,
                'error': error_msg,
                'run_id': run_id,
                'company_name': company_name,
                'execution_time_ms': 0
            }

    async def _execute_company_search_workflow(self, search_params: Dict[str, Any], run_id: str, user_id: str,
                                             shared_output_file: str, db: ProspectingDB, postgres_enabled: bool, session_context: SessionContext, workflow_type: str) -> Dict[str, Any]:
        """
        Execute the company search workflow for general search requests.
        Returns search results for user selection.
        """
        logger.info("Company search workflow started", extra={"run_id": run_id, "search_params": search_params, "workflow_type": workflow_type})
        print(f"🔍 Executing company search workflow")
        
        # Start the prospecting run to ensure the run_id exists in the database
        if postgres_enabled and db:
            # Prepare search parameters for storage
            search_params_for_storage = {
                'investor_type': search_params.get('investor_type', 'VC'),
                'investor_focus': search_params.get('investor_focus', 'Technology'),
                'investment_stage': search_params.get('investment_stage', 'Series A'),
                'location': search_params.get('location', 'United States'),
                'additional_company_info': search_params.get('additional_company_info', '')
            }
            try:
                await db.start_run(
                    run_id=run_id,
                    user_id=user_id,
                    session_id=session_context.session_id,
                    search_params=search_params_for_storage,  # Store search parameters
                    company_name=None,  # NULL during search phase
                    company_id=None,     # NULL during search phase
                    workflow_type=workflow_type
                )
                print(f"✅ Started prospecting run: {run_id}")
            except Exception as e:
                print(f"⚠️ Warning: Failed to start prospecting run: {e}")

            # Prepare search parameters - include additional_company_info
            search_params_for_agent = {
                'investor_type': search_params.get('investor_type', 'VC'),
                'investor_focus': search_params.get('investor_focus', 'Technology'),
                'investment_stage': search_params.get('investment_stage', 'Series A'),
                'location': search_params.get('location', 'United States'),
                'additional_company_info': search_params.get('additional_company_info', '')  # Pass additional info
            }
            
            # Execute company search
            print(f"🔍 Step 1: Company search with parameters: {search_params_for_agent}")
            search_result = await self.sub_agents['company_search'].execute(
                company_search_params=search_params_for_agent,
                run_id=run_id,
                user_id=user_id,
                shared_output_file=shared_output_file,
                db=db,
                postgres_enabled=postgres_enabled,
                session_id=session_context.session_id
            )
            
            if not search_result['success']:
                logger.error("Company search failed", extra={"run_id": run_id, "error": search_result.get('error', 'Unknown error')})
                return {
                    'success': False,
                    'error': f"Company search failed: {search_result.get('error', 'Unknown error')}",
                    'run_id': run_id,
                    'user_id': user_id,
                    'execution_time_ms': search_result.get('execution_time_ms', 0)
                }
            
            # Format search results
            companies = search_result.get('search_results', {}).get('companies', [])
            
            if not companies:
                logger.warning("No companies found in search results", extra={"run_id": run_id})
                return {
                    'success': False,
                    'error': 'No companies found in search results',
                    'run_id': run_id,
                    'user_id': user_id,
                    'execution_time_ms': search_result.get('execution_time_ms', 0)
                }
            
            print(f"✅ Company search completed - found {len(companies)} companies")
            print(f"📋 Please select a company (1-{len(companies)}) for enrichment")
            
            logger.info("Company search completed successfully", extra={"run_id": run_id, "companies_found": len(companies)})
        # Do NOT set 100% here; reserve 100% for final workflow completion
        # Ensure we always return results to the caller
        return {
            'success': True,
            'workflow_type': 'company_search',
            'run_id': run_id,
            'user_id': user_id,
            'companies': companies,
            'companies_found': len(companies),
            'search_params': search_params_for_agent,
            'execution_time_ms': search_result.get('execution_time_ms', 0),
            'search_output_file': shared_output_file,
            'next_step': 'user_selection_required'
        }
            
        # No broad catch here; exceptions bubble to caller which already handles

    async def handle_user_company_selection(self, run_id: str, user_id: str, selected_company_index: int = None, session_context: SessionContext = None) -> Dict[str, Any]:
        """
        Handle user company selection and proceed with enrichment.
        
        Args:
            run_id: The run ID from the search phase
            user_id: User identifier for multi-tenant isolation
            selected_company_index: Company index to select (1-based). If None, prompts for console input.
            session_context: Session context for session-aware execution
            
        Returns:
            Dict containing enrichment results with web app compatible format
        """
        print(f"🎯 Handling user company selection for run: {run_id}")
        # Early verification: ensure progress is reset for enrichment phase
        try:
            # Use global DB if not already set
            if not self.db:
                self.db = await get_global_db()
            from app.utils.progress_store import ProgressStore
            await ProgressStore.instance().reset_progress(self.db, run_id)
            hard_after_reset = await ProgressStore.instance().get_progress(self.db, run_id)
            display_after_reset = await ProgressStore.instance().get_display_progress(self.db, run_id, workflow_type='specific_company', status='processing')
            print(f"🧪 Progress reset verification — hard: {hard_after_reset}%, display: {display_after_reset}%")
        except Exception as e:
            print(f"⚠️ Progress reset verification failed: {e}")
        
        try:
            # Always get global database instance for selection path
            self.db = await get_global_db()
            print(f"🔗 ProspectingOrchestrator.selection: Using global database instance: {id(self.db)}")
            
            # Extract parent run_id if this is a company selection run_id
            parent_run_id = run_id
            if "_sel_" in run_id:
                # Extract parent run_id from selection run_id (e.g., "session_abc_run_001_sel_001" -> "session_abc_run_001")
                parent_run_id = run_id.split("_sel_")[0]
                print(f"🎯 Detected company selection run_id, using parent: {parent_run_id}")
            
            # Retrieve search results from database using parent run_id
            search_results_list = await self.db.get_company_search_results(user_id, parent_run_id, session_context.session_id) if self.db else None
            
            if not search_results_list or not isinstance(search_results_list, list) or len(search_results_list) == 0:
                return {
                    'success': False,
                    'error': 'No search results found for this run',
                    'run_id': run_id,
                    'user_id': user_id,
                    'workflow_type': 'company_selection_error'
                }
            
            # Get the most recent search result (first in the list)
            search_results = search_results_list[0]
            
            # Extract companies from the search_results JSONB field
            companies = []
            if search_results.get('search_results'):
                try:
                    search_results_data = json.loads(search_results['search_results']) if isinstance(search_results['search_results'], str) else search_results['search_results']
                    companies = search_results_data.get('companies', [])
                    print(f"🔍 Extracted {len(companies)} companies from search_results field")
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"⚠️ Error parsing search_results from database: {e}")
                    companies = []
            
            if not companies:
                return {
                    'success': False,
                    'error': f'No companies found in search results. Search Results field: {type(search_results.get("search_results"))}',
                    'run_id': run_id,
                    'user_id': user_id,
                    'workflow_type': 'company_selection_error'
                }
            
            # Display companies for selection (console-friendly format)
            print(f"\n📋 Available Companies ({len(companies)} found):")
            print("-" * 60)
            for i, company in enumerate(companies, 1):
                print(f"{i:2d}. {company.get('company_name', 'Unknown')}")
                print(f"     Domain: {company.get('company_domain', 'N/A')}")
                print(f"     Type: {company.get('investor_type', 'N/A')}")
                print(f"     Focus: {company.get('investor_focus', 'N/A')}")
                print(f"     Location: {company.get('location', 'N/A')}")
                print()
            
            # Handle company selection
            if selected_company_index is None:
                # Console input mode (testing)
                while True:
                    try:
                        user_input = input(f"🎯 Select a company (1-{len(companies)}): ").strip()
                        selected_company_index = int(user_input)
                        
                        if 1 <= selected_company_index <= len(companies):
                            break
                        else:
                            print(f"❌ Please enter a number between 1 and {len(companies)}")
                    except ValueError:
                        print("❌ Please enter a valid number")
                    except KeyboardInterrupt:
                        print("\n❌ Selection cancelled")
                        return {
                            'success': False,
                            'error': 'User cancelled selection',
                            'run_id': run_id,
                            'user_id': user_id,
                            'workflow_type': 'company_selection_cancelled'
                        }
            else:
                # Programmatic selection (web app mode)
                if not (1 <= selected_company_index <= len(companies)):
                    return {
                        'success': False,
                        'error': f'Invalid company index. Must be between 1 and {len(companies)}',
                        'run_id': run_id,
                        'user_id': user_id,
                        'workflow_type': 'company_selection_error'
                    }
            
            # Get selected company data
            selected_company = companies[selected_company_index - 1]
            company_name = selected_company.get('company_name', 'Unknown Company')
            
            print(f"✅ Selected company: {company_name}")
            print(f"🔄 Starting enrichment process...")
            
            # Update prospecting run with selected company information
            if get_enable_postgres_storage() and self.db:
                try:
                    # Generate a company_id for the selected company
                    company_id_for_run = f"selected_{selected_company.get('company_domain', 'unknown').replace('.', '_')}"
                    
                    await self.db.update_run_company(
                        run_id=run_id,
                        company_name=company_name,
                        company_id=company_id_for_run
                    )
                    print(f"✅ Updated prospecting run with selected company: {company_name}")
                except Exception as e:
                    print(f"⚠️ Warning: Failed to update prospecting run with company selection: {e}")
            
            # Store session interaction if session context is provided
            await self.store_session_interaction(
                session_context,
                f"{run_id}_selection_{selected_company_index}",
                f"Company selection: {company_name} (index {selected_company_index})",
                "company_selection"
            )
            
            # Create output file for enrichment when debugging is enabled
            safe_company_name = company_name.replace('/', '-').replace(' ', '_')[:50]
            enrichment_output_file = None
            if self.enable_debugging:
                try:
                    debug_dir = "output/prospecting"
                    os.makedirs(debug_dir, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    enrichment_output_file = f"{debug_dir}/debug_{timestamp}.md"
                    print(f"🐛 Debug file created for selection flow: {enrichment_output_file}")
                except Exception as e:
                    print(f"⚠️ Failed to create debug file for selection flow: {e}")
            
            # Prepare company data for enrichment workflow
            # Use separate hq_city and hq_country_region from search results
            # Only extract metadata domain if it's non-null and non-empty
            raw_domain = selected_company.get('company_domain')
            search_metadata_domain = None
            if raw_domain and raw_domain.strip():  # Check for non-null and non-empty
                # Normalize search metadata domain to URL format if it's just a domain
                if not raw_domain.startswith(('http://', 'https://')):
                    search_metadata_domain = f"https://{raw_domain}"
                else:
                    search_metadata_domain = raw_domain
            
            company_data_for_workflow = {
                'name': company_name,
                'location': selected_company.get('location', 'Unknown'),  # Keep for backward compatibility
                'hq_city': selected_company.get('hq_city'),
                'hq_country': selected_company.get('hq_country_region'),  # Map hq_country_region to hq_country
                'focus_area': selected_company.get('investor_focus', 'General prospecting'),
                'investor_type': selected_company.get('investor_type', ''),
                'search_metadata_domain': search_metadata_domain,
                'output_file': enrichment_output_file
            }
            
            # Execute the enrichment workflow for the selected company
            print(f"🔍 Step 1: Domain discovery for {company_name}")
            
            # Update status to processing
            if get_enable_postgres_storage() and self.db:
                try:
                    await self.db.update_run_status(run_id, 'processing')
                    print(f"✅ Updated prospecting run status to: processing")
                except Exception as e:
                    print(f"⚠️ Warning: Failed to update run status: {e}")
            
            domain_discovery_result = await self._discover_domain_and_generate_id(company_data_for_workflow, enrichment_output_file)
            
            # Early exit if no valid domain found
            found_url = domain_discovery_result.get('found_url')
            if (not domain_discovery_result['success'] or 
                found_url is None or 
                (isinstance(found_url, str) and found_url.strip().lower() in ('null', '[null]', 'none', '')) or
                (isinstance(found_url, list) and (not found_url or found_url[0] in (None, 'null', '[null]', 'none', '')))):
                error_msg = "No valid company domain could be found. Sub-agents were not executed."
                print(f"❌ {error_msg}")
                return {
                    'success': False,
                    'error': error_msg,
                    'run_id': run_id,
                    'company_name': company_name,
                    'execution_time_ms': 0,
                    'workflow_type': 'company_selection_enrichment_failed'
                }
            
            company_id = domain_discovery_result['company_id']
            found_url = domain_discovery_result['found_url']
            found_by_perplexity = domain_discovery_result['found_by_perplexity']
            
            # Store company in PostgreSQL if enabled
            if get_enable_postgres_storage() and self.db:
                try:
                    company_data_for_db = {
                        'name': company_name,
                        'website_url': found_url,
                        'location': selected_company.get('location'),  # Keep for backward compatibility
                        'hq_city': selected_company.get('hq_city'),
                        'hq_country': selected_company.get('hq_country_region'),
                        'focus_area': selected_company.get('investor_focus')
                    }
                    await self.db.store_company(
                        run_id=run_id,
                        company_data=company_data_for_db,
                        company_id=company_id,
                        user_id=user_id,
                        session_id=session_context.session_id
                    )
                    print(f"✅ Company stored in PostgreSQL with ID: {company_id}")
                except Exception as e:
                    print(f"⚠️ Error storing company in PostgreSQL: {e}")
            
            # Step 2: Phase 1 - Parallel Data Collection
            print(f"🔄 Step 2: Phase 1 - Parallel data collection")
            phase1_result = await self._run_phase1_parallel(
                company_data_for_workflow, run_id, company_id, domain_discovery_result['found_url'], 
                domain_discovery_result['found_urls'], domain_discovery_result['found_by_perplexity'], 
                enrichment_output_file, user_id, session_id=session_context.session_id
            )
            
            if not phase1_result['success']:
                return {
                    'success': False,
                    'error': f"Phase 1 failed: {phase1_result['error']}",
                    'run_id': run_id,
                    'company_name': company_name,
                    'execution_time_ms': 0,
                    'workflow_type': 'company_selection_enrichment_failed'
                }
            
            # Step 3: Phase 2 - Parallel Enrichment
            print(f"🔄 Step 3: Phase 2 - Parallel enrichment")
            phase2_result = await self._run_phase2_parallel(
                company_data_for_workflow, run_id, company_id, enrichment_output_file, user_id, session_id=session_context.session_id, session_context=session_context
            )
            
            if not phase2_result['success']:
                return {
                    'success': False,
                    'error': f"Phase 2 failed: {phase2_result['error']}",
                    'run_id': run_id,
                    'company_name': company_name,
                    'execution_time_ms': 0,
                    'workflow_type': 'company_selection_enrichment_failed'
                }
            
            # Step 4: Generate Summary Report
            total_execution_time_ms = domain_discovery_result.get('execution_time_ms', 0) + \
                                    phase1_result.get('execution_time_ms', 0) + \
                                    phase2_result.get('execution_time_ms', 0)
            
            summary_result = await self._generate_summary_report(
                company_data=company_data_for_workflow,
                run_id=run_id,
                company_id=company_id,
                phase1_result=phase1_result,
                phase2_result=phase2_result,
                execution_time_ms=total_execution_time_ms,
                shared_output_file=enrichment_output_file,
                session_context=session_context
            )
            
            print(f"✅ Company selection and enrichment completed successfully!")
            
            # Update status to completed and set end_time
            if get_enable_postgres_storage() and self.db:
                try:
                    await self.db.complete_prospecting_run(run_id, user_id, session_context.session_id, total_execution_time_ms)
                    print(f"✅ Completed prospecting run with end_time set")
                    
                    # Increment agent run tally for completed company_selection workflow
                    try:
                        rate_limiter = RateLimiter()
                        await rate_limiter.increment_request_count(user_id)
                        logger.info(
                            "Agent run tally incremented for company selection",
                            extra={
                                "run_id": run_id,
                                "user_id": user_id,
                                "workflow_type": "company_selection"
                            }
                        )
                    except Exception as tally_error:
                        # Non-fatal: log but don't fail the workflow
                        logger.warning(
                            "Failed to increment agent run tally for company selection",
                            extra={
                                "run_id": run_id,
                                "user_id": user_id,
                                "error": str(tally_error)
                            }
                        )
                except Exception as e:
                    print(f"⚠️ Warning: Failed to complete prospecting run: {e}")
            
            # Return web app compatible response format
            return {
                'success': True,
                'workflow_type': 'company_selection_enrichment',
                'run_id': run_id,
                'user_id': user_id,
                'selected_company_index': selected_company_index,
                'selected_company': selected_company,
                'company_name': company_name,
                'company_id': company_id,
                'execution_time_ms': total_execution_time_ms,
                'output_file': enrichment_output_file,
                'phase1_results': phase1_result,
                'phase2_results': phase2_result,
                'summary': summary_result,
                'enrichment_status': 'completed',
                'postgres_enabled': get_enable_postgres_storage()
            }
            
        except Exception as e:
            error_msg = f"Company selection and enrichment failed: {str(e)}"
            print(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'run_id': run_id,
                'user_id': user_id,
                'execution_time_ms': 0,
                'workflow_type': 'company_selection_enrichment_failed'
            }
        finally:
            # Note: Database connection is managed globally, no need to close here
            pass

    # Reuse existing methods from original orchestrator
    async def _discover_domain_and_generate_id(self, company_data: Dict, shared_output_file: str) -> Dict[str, Any]:
        """
        Discover company domain and generate company_id once at the beginning.
        """
        try:
            company_name = company_data['name']
            
            # Attempt to find company homepage using Perplexity
            print(f"🔍 Searching for {company_name} homepage...")
            
            try:
                # Prepare web search config for Perplexity
                investor_type = company_data.get('investor_type', '')
                investor_type_context = f" (this company is an {investor_type})" if investor_type else ""
                web_search_config = {
                    "query_template": "official website {company_name} {location}{investor_type_context}",
                    "search_type_description": "company homepage or official website for {company_name}",
                    "output_format_example": '["https://company.com"]',
                    "max_results": 1,
                    "investor_type": investor_type
                }
                
                # Use location for domain discovery (backward compatibility)
                location_for_domain = company_data.get('location') or ""
                # Also include hq_city and hq_country if available for better domain discovery
                if company_data.get('hq_city') and company_data.get('hq_country'):
                    location_for_domain = f"{company_data.get('hq_city')}, {company_data.get('hq_country')}"
                elif company_data.get('hq_city'):
                    location_for_domain = company_data.get('hq_city')
                elif company_data.get('hq_country'):
                    location_for_domain = company_data.get('hq_country')
                
                domain_result = await find_company_homepage_url_perplexity.ainvoke({
                    "company_name": company_name,
                    "location": location_for_domain,
                    "focus_area": company_data['focus_area'] or "",
                    "investor_type": company_data.get('investor_type', ''),
                    "web_search_config": web_search_config
                })
                
                # Get domain from search metadata (if available)
                search_metadata_domain = company_data.get('search_metadata_domain', '')
                
                # Normalize domain for comparison (remove protocol, www., trailing slashes)
                def normalize_domain_for_comparison(domain: str) -> str:
                    """Normalize domain for deduplication comparison."""
                    if not domain:
                        return ""
                    domain = domain.lower().strip()
                    # Remove protocol
                    if domain.startswith('http://'):
                        domain = domain[7:]
                    elif domain.startswith('https://'):
                        domain = domain[8:]
                    # Remove www.
                    if domain.startswith('www.'):
                        domain = domain[4:]
                    # Remove trailing slash and path
                    domain = domain.split('/')[0].split('?')[0]
                    return domain
                
                # Handle both single domain (string) and multiple domains (list) from Perplexity
                perplexity_domains = []
                if isinstance(domain_result, list):
                    perplexity_domains = domain_result
                elif domain_result:
                    perplexity_domains = [domain_result]
                
                # Build final domain list: Perplexity domains first, then search metadata domain (deduplicated)
                found_urls = []
                normalized_seen = set()
                
                # Add Perplexity domains first (deduplicated)
                for domain in perplexity_domains:
                    if domain:
                        normalized = normalize_domain_for_comparison(domain)
                        if normalized and normalized not in normalized_seen:
                            found_urls.append(domain)
                            normalized_seen.add(normalized)
                
                # Add search metadata domain after Perplexity domains if available
                if search_metadata_domain:
                    normalized_metadata = normalize_domain_for_comparison(search_metadata_domain)
                    if normalized_metadata and normalized_metadata not in normalized_seen:
                        found_urls.append(search_metadata_domain)
                        normalized_seen.add(normalized_metadata)
                        print(f"✅ Added search metadata domain: {search_metadata_domain}")
                
                # Set primary domain (first in list)
                if found_urls:
                    found_url = found_urls[0]
                    print(f"✅ Found {len(found_urls)} unique domain(s): {found_urls}")
                    print(f"🎯 Using primary domain: {found_url}")
                else:
                    found_url = None
                    print(f"⚠️ No domains found")
                
                found_by_perplexity = True
                
            except Exception as e:
                print(f"⚠️ Perplexity homepage search failed: {e}")
                # Fallback to basic URL guess
                found_url = f"https://www.{company_name.lower().replace(' ', '')}.com"
                found_urls = [found_url]
                found_by_perplexity = False
                print(f"🔄 Using fallback URL: {found_url}")
            
            # Generate company_id from primary domain
            company_id = generate_company_id_from_domain(found_url)
            print(f"🆔 Generated company_id: {company_id}")
            
            return {
                'success': True,
                'company_id': company_id,
                'found_url': found_url,
                'found_urls': found_urls,
                'domain_count': len(found_urls),
                'found_by_perplexity': found_by_perplexity
            }
            
        except Exception as e:
            error_msg = f"Domain discovery failed: {str(e)}"
            print(f"❌ {error_msg}")
            
            return {
                'success': False,
                'error': error_msg
            }

    async def _run_phase1_parallel(self, company_data: Dict, run_id: str, company_id: str, 
                                 found_url: str, found_urls: List[str], found_by_perplexity: bool, 
                                 shared_output_file: str, user_id: str = None, session_id: str = None) -> Dict[str, Any]:
        """
        Phase 1: Run Web Research and CoreSignal agents in parallel.
        """
        logger.info("Phase 1 parallel execution started", extra={"run_id": run_id, "company_id": company_id})
        print("🔄 Running Phase 1 agents in parallel...")
        
        try:
            # Run both agents in parallel using asyncio.gather
            web_research_task = self.sub_agents['web_research'].execute(
                company_data, run_id=run_id, company_id=company_id,
                found_url=found_url, found_urls=found_urls, found_by_perplexity=found_by_perplexity,
                shared_output_file=shared_output_file, user_id=user_id, session_id=session_id
            )
            
            coresignal_task = self.sub_agents['coresignal'].execute(
                company_data, run_id=run_id, company_id=company_id, 
                found_url=found_url, found_urls=found_urls, user_id=user_id, session_id=session_id
            )

            youtube_task = self.sub_agents['youtube_media'].execute(
                company_data, run_id=run_id, company_id=company_id,
                shared_output_file=shared_output_file, db=self.db, postgres_enabled=get_enable_postgres_storage(),
                user_id=user_id, session_id=session_id, youtube_url=found_url
            )
            
            # Wait for both to complete
            web_research_result, coresignal_result, youtube_result = await asyncio.gather(
                web_research_task, coresignal_task, youtube_task, return_exceptions=True
            )
            
            # Handle any exceptions
            if isinstance(web_research_result, Exception):
                print(f"❌ Web Research Agent failed: {web_research_result}")
                web_research_result = {'success': False, 'error': str(web_research_result)}
            
            if isinstance(coresignal_result, Exception):
                print(f"❌ CoreSignal Agent failed: {coresignal_result}")
                coresignal_result = {'success': False, 'error': str(coresignal_result)}

            if isinstance(youtube_result, Exception):
                print(f"❌ YouTube Media Agent failed: {youtube_result}")
                youtube_result = {'success': False, 'error': str(youtube_result)}
            
            print(f"✅ Phase 1 completed - Web Research: {'✅' if web_research_result.get('success') else '❌'}, CoreSignal: {'✅' if coresignal_result.get('success') else '❌'}, YouTube: {'✅' if youtube_result.get('success') else '❌'}")

            logger.info("Phase 1 parallel execution completed", extra={
                "run_id": run_id, 
                "company_id": company_id, 
                "web_research_success": web_research_result.get('success', False),
                "coresignal_success": coresignal_result.get('success', False),
                "youtube_success": youtube_result.get('success', False)
            })

            return {
                'success': True,
                'web_research_result': web_research_result,
                'coresignal_result': coresignal_result,
                'youtube_result': youtube_result
            }
            
        except Exception as e:
            error_msg = f"Phase 1 parallel execution failed: {str(e)}"
            print(f"❌ {error_msg}")
            logger.exception("Phase 1 parallel execution failed", extra={"run_id": run_id, "company_id": company_id})
            return {
                'success': False,
                'error': error_msg
            }

    async def _run_phase2_parallel(self, company_data: Dict, run_id: str, company_id: str, 
                                 shared_output_file: str, user_id: str, session_id: str, session_context: SessionContext) -> Dict[str, Any]:
        """
        Phase 2: Run Company Enrichment and Person Enrichment agents in parallel.
        """
        logger.info("Phase 2 parallel execution started", extra={"run_id": run_id, "company_id": company_id})
        print("🔄 Running Phase 2 agents in parallel...")
        try:
            # Run all enrichment agents in parallel using asyncio.gather
            company_enrich_task = self.sub_agents['company_enrich'].execute(
                company_data, run_id, company_id, shared_output_file, self.db, get_enable_postgres_storage(), user_id, session_id
            )
            person_enrich_task = self.sub_agents['person_enrich'].execute(
                company_data, run_id, company_id, shared_output_file, self.db, get_enable_postgres_storage(), user_id, session_id
            )
            ria_detection_task = self._ria_detection_task(
                company_data, run_id, user_id, session_id, company_id
            )
            
            # Wait for all to complete
            company_enrich_result, person_enrich_result, ria_detection_result = await asyncio.gather(
                company_enrich_task, person_enrich_task, ria_detection_task, return_exceptions=True
            )
            
            # Handle any exceptions
            if isinstance(company_enrich_result, Exception):
                print(f"❌ Company Enrich Agent failed: {company_enrich_result}")
                company_enrich_result = {'success': False, 'error': str(company_enrich_result)}
            
            if isinstance(person_enrich_result, Exception):
                print(f"❌ Person Enrich Agent failed: {person_enrich_result}")
                person_enrich_result = {'success': False, 'error': str(person_enrich_result)}
            
            if isinstance(ria_detection_result, Exception):
                print(f"❌ RIA Detection Agent failed: {ria_detection_result}")
                ria_detection_result = {'success': False, 'error': str(ria_detection_result)}
            
            print(f"✅ Phase 2 completed - Company Enrich: {'✅' if company_enrich_result.get('success') else '❌'}, Person Enrich: {'✅' if person_enrich_result.get('success') else '❌'}, RIA Detection: {'✅' if ria_detection_result.get('success') else '❌'}")
        
            # Store RIA detection result in session context
            if ria_detection_result.get('success'):
                session_context.ria_detection_result = ria_detection_result.get('result', {})
            else:
                session_context.ria_detection_result = {
                    'is_ria': False,
                    'crd_number': None,
                    'method': 'error'
                }
        
            logger.info("Phase 2 parallel execution completed", extra={
                "run_id": run_id, 
                "company_id": company_id, 
                "company_enrich_success": company_enrich_result.get('success', False),
                "person_enrich_success": person_enrich_result.get('success', False),
                "ria_detection_success": ria_detection_result.get('success', False)
            })

            # Update component statuses for FE early-stop logic
            try:
                await ProgressStore.instance().update_component_status(self.db, run_id, "company_enrichment", "success" if company_enrich_result.get('success') else "failed", None if company_enrich_result.get('success') else "COMPANY_ENRICH_FAILED", None)
                await ProgressStore.instance().update_component_status(self.db, run_id, "person_enrichment", "success" if person_enrich_result.get('success') else "failed", None if person_enrich_result.get('success') else "PEOPLE_NOT_FOUND", None)
                await ProgressStore.instance().update_component_status(self.db, run_id, "ria_detection", "success" if ria_detection_result.get('success') else "failed", None if ria_detection_result.get('success') else "RIA_DETECTION_FAILED", None)
            except Exception:
                pass

            # Ensure persisted results exist; if not, mark as failed with NO_PERSISTED_RESULTS
            try:
                # Company verification
                if company_enrich_result.get('success'):
                    try:
                        company_data_check = await self.db.get_company_enrichment_by_run(run_id, user_id)
                        if not company_data_check:
                            await ProgressStore.instance().update_component_status(self.db, run_id, "company_enrichment", "failed", "NO_PERSISTED_RESULTS", "Company enrichment reported success but no results were stored")
                    except Exception:
                        # If check fails, do not override
                        pass
                # Person verification
                if person_enrich_result.get('success'):
                    try:
                        person_data_check = await self.db.get_person_enrichment_by_run(run_id, user_id)
                        has_person = bool(person_data_check) and isinstance(person_data_check, list) and len(person_data_check) > 0
                        if not has_person:
                            await ProgressStore.instance().update_component_status(self.db, run_id, "person_enrichment", "failed", "NO_PERSISTED_RESULTS", "Person enrichment reported success but no results were stored")
                    except Exception:
                        pass
            except Exception:
                pass
        
            return {
                'success': True,
                'company_enrich_result': company_enrich_result,
                'person_enrich_result': person_enrich_result,
                'ria_detection_result': ria_detection_result
            }
            
        except Exception as e:
            error_msg = f"Phase 2 parallel execution failed: {str(e)}"
            print(f"❌ {error_msg}")
            logger.exception("Phase 2 parallel execution failed", extra={"run_id": run_id, "company_id": company_id})
            return {
                'success': False,
                'error': error_msg
            }

    async def _ria_detection_task(self, company_data: Dict[str, Any], run_id: str, 
                                 user_id: str, session_id: str, company_id: str) -> Dict[str, Any]:
        """Run RIA detection in parallel with other enrichment tasks."""
        try:
            ria_agent = RIADetectionAgent()
            result = await ria_agent.execute(
                company_data=company_data,
                run_id=run_id,
                user_id=user_id,
                session_id=session_id,
                company_id=company_id,
                db=self.db
            )
            return result
        except Exception as e:
            return {
                'success': False,
                'error': f'RIA detection failed: {str(e)}',
                'agent_name': 'RIA Detection'
            }

    async def _generate_summary_report(self, company_data: Dict, run_id: str, company_id: str,
                                     phase1_result: Dict, phase2_result: Dict, 
                                     execution_time_ms: int, shared_output_file: str, session_context: SessionContext) -> Dict[str, Any]:
        """
        Generate a comprehensive summary report of the prospecting results.
        """
        try:
            company_name = company_data['name']
            
            print(f"✅ Summary report generated for {company_name}")
        
            return {
                'success': True,
                'summary_file': shared_output_file,
                'total_agents_successful': sum([
                    1 for result in [
                        phase1_result.get('web_research_result', {}),
                        phase1_result.get('coresignal_result', {}),
                        phase2_result.get('company_enrich_result', {}),
                        phase2_result.get('person_enrich_result', {}),
                        phase2_result.get('ria_detection_result', {})
                    ] if result.get('success')
                ]),
                'ria_summary': {
                    'is_ria': getattr(session_context, 'ria_detection_result', {}).get('is_ria', False),
                    'crd_number': getattr(session_context, 'ria_detection_result', {}).get('crd_number'),
                    'has_ria_data': bool(getattr(session_context, 'ria_detection_result', {}).get('crd_number'))
                }
            }
            
        except Exception as e:
            error_msg = f"Summary report generation failed: {str(e)}"
            print(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }

    async def execute_interactive(self, user_id: str = None) -> None:
        """
        Execute the orchestrator in interactive mode with complete workflow handling and session management.
        This method runs a continuous loop that handles all workflow types including company selection.
        
        Args:
            user_id: User identifier for multi-tenant isolation. If None, generates a unique ID.
        """
        print("🚀 Prospecting Orchestrator v2 - Interactive Mode")
        print("=" * 60)
        print("This mode handles the complete workflow including company selection.")
        print("Type 'quit' to exit.")
        print()
        print("💡 You can try these types of prompts:")
        print("   • Specific company: 'Research Sequoia Capital'")
        print("   • General search: 'Find VC firms in London focusing on fintech'")
        print("   • Off-topic: 'What's the weather like?'")
        print()
        
        # Generate a unique user ID if not provided
        if not user_id:
            user_id = f"interactive_user_{int(time.time())}"
        
        # Start a new session
        session_context = await self.start_session(user_id)
        
        print(f"👤 User ID: {user_id}")
        print(f"🆔 Session ID: {session_context.session_id}")
        print()
        
        try:
            while True:
                try:
                    # Get user input
                    prompt = input("📝 Enter your prompt: ").strip()
                    
                    if prompt.lower() in ['quit', 'exit', 'q']:
                        print("👋 Goodbye!")
                        break
                    
                    if not prompt:
                        print("⚠️ Please enter a valid prompt.")
                        continue
                    
                    print(f"\n🔍 Processing: '{prompt}'")
                    print("-" * 40)
                    
                    # Execute the orchestrator with session context
                    result = await self.execute(prompt=prompt, user_id=user_id, session_context=session_context)
                    
                    if result['success']:
                        print("✅ Success!")
                        print(f"   Workflow Type: {result.get('workflow_type', 'unknown')}")
                        print(f"   Run ID: {result['run_id']}")
                        print(f"   Session ID: {result.get('session_id', 'N/A')}")
                        print(f"   Interaction #: {result.get('interaction_number', 'N/A')}")
                        
                        if result.get('workflow_type') == 'company_search':
                            print(f"   Companies Found: {len(result.get('companies', []))}")
                            print(f"   Next Step: {result.get('next_step', 'N/A')}")
                            print(f"   Status: Waiting for company selection...")
                            
                            # Handle company selection
                            companies = result.get('companies', [])
                            if companies:
                                print(f"\n📋 Available Companies ({len(companies)} found):")
                                print("-" * 60)
                                for i, company in enumerate(companies, 1):
                                    print(f"{i:2d}. {company.get('company_name', 'Unknown')}")
                                    print(f"     Domain: {company.get('company_domain', 'N/A')}")
                                    print(f"     Type: {company.get('investor_type', 'N/A')}")
                                    print(f"     Focus: {company.get('investor_focus', 'N/A')}")
                                    print(f"     Location: {company.get('location', 'N/A')}")
                                    print()
                                
                                # Get user selection
                                while True:
                                    try:
                                        selection = input(f"🎯 Select a company to enrich (1-{len(companies)}) or 'skip': ").strip()
                                        
                                        if selection.lower() in ['skip', 's', 'no']:
                                            print("⏭️ Skipping company selection.")
                                            break
                                        
                                        selected_index = int(selection)
                                        if 1 <= selected_index <= len(companies):
                                            print(f"✅ Selected company: {companies[selected_index-1].get('company_name')}")
                                            print("🔄 Starting enrichment process...")
                                            
                                            # Call the company selection handler with session context
                                            selection_result = await self.handle_user_company_selection(
                                                run_id=result['run_id'],
                                                user_id=user_id,
                                                selected_company_index=selected_index,
                                                session_context=session_context
                                            )
                                            
                                            if selection_result['success']:
                                                print("✅ Company enrichment completed!")
                                                print(f"   Company: {selection_result.get('company_name', 'Unknown')}")
                                                print(f"   Company ID: {selection_result.get('company_id', 'N/A')}")
                                                print(f"   Output File: {selection_result.get('output_file', 'N/A')}")
                                                print(f"   Execution Time: {selection_result.get('execution_time_ms', 0)}ms")
                                                print(f"   Session ID: {selection_result.get('session_id', 'N/A')}")
                                            else:
                                                print("❌ Company enrichment failed!")
                                                print(f"   Error: {selection_result.get('error', 'Unknown error')}")
                                            
                                            break
                                        else:
                                            print(f"❌ Please enter a number between 1 and {len(companies)}")
                                    except ValueError:
                                        print("❌ Please enter a valid number or 'skip'")
                                    except KeyboardInterrupt:
                                        print("\n⏭️ Skipping company selection.")
                                        break
                        
                        elif result.get('workflow_type') == 'off_topic':
                            print(f"   Message: {result.get('message', 'No message provided')}")
                            print(f"   Next Step: {result.get('next_step', 'N/A')}")
                            print(f"   Status: Waiting for user input...")
                            print()
                            print("💡 The system is now waiting for your next prompt.")
                            print("   Try asking about a specific company or search criteria.")
                            
                        elif result.get('workflow_type') == 'specific_company':
                            print(f"   Company: {result.get('company_name', 'Unknown')}")
                            print(f"   Company ID: {result.get('company_id', 'N/A')}")
                            print(f"   Output File: {result.get('output_file', 'N/A')}")
                            print(f"   Status: Enrichment completed!")
                            
                    else:
                        print("❌ Failed!")
                        print(f"   Error: {result.get('error', 'Unknown error')}")
                        
                except KeyboardInterrupt:
                    print("\n👋 Goodbye!")
                    break
                except Exception as e:
                    print(f"❌ Exception: {e}")
                    import traceback
                    traceback.print_exc()
                
                print("\n" + "=" * 60)
        
        finally:
            # End the session when the loop exits
            await self.end_session(session_context)


async def main():
    """
    Main function for the v2 orchestrator.
    Runs in interactive mode by default.
    """
    print("🚀 Prospecting Orchestrator v2")
    print("=" * 60)
    print("Starting interactive mode...")
    print()
    
    # Generate a unique user ID for this session
    user_id = f"session_user_{int(time.time())}"
    
    # Run interactive mode
    orchestrator = ProspectingOrchestrator()
    await orchestrator.execute_interactive(user_id=user_id)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Error: {e}")
        import sys
        sys.exit(1) 

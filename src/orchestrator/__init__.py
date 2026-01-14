# orchestrator/__init__.py
"""
Orchestrator module for CI/CD AI assistant.

This module coordinates signal processing:
  - ContextBuilder: Builds code context for LLM processing
  - Prioritizer: Groups and prioritizes signals
  - FixPlanner: Converts signals to executable fix plans (requires httpx)
"""
from orchestrator.context_builder import ContextBuilder, FileSnippet
from orchestrator.prioritizer import (
    Prioritizer,
    SignalGroup,
    SIGNAL_TYPE_PRIORITY,
    default_tool_resolver,
)

# Fix planner requires additional dependencies (httpx for LLM calls)
# Import conditionally to allow core functionality without full deps
try:
    from orchestrator.fix_planner import (
        AUTO_APPLY_FORMAT_FIXES,
        FixPlanner,
        PlannerResult,
        create_fix_plan,
        create_format_fix_plan_direct,
    )
    _HAS_FIX_PLANNER = True
except ImportError:
    _HAS_FIX_PLANNER = False
    AUTO_APPLY_FORMAT_FIXES = True  # Default value
    FixPlanner = None
    PlannerResult = None
    create_fix_plan = None
    create_format_fix_plan_direct = None

__all__ = [
    # Context Builder
    "ContextBuilder",
    "FileSnippet",
    # Prioritizer
    "Prioritizer",
    "SignalGroup",
    "SIGNAL_TYPE_PRIORITY",
    "default_tool_resolver",
    # Fix Planner (may be None if dependencies missing)
    "FixPlanner",
    "PlannerResult",
    "AUTO_APPLY_FORMAT_FIXES",
    "create_fix_plan",
    "create_format_fix_plan_direct",
]

# orchestrator/fix_planner.py
"""
Fix Planner - Converts FixSignals into executable FixPlans.

This module provides two pathways for generating fix plans:

1. **Direct Application (no LLM)**: For FORMAT signals and other safe,
   deterministic fixes. Converts FixSignal.fix directly into FixPlan.

2. **LLM-Assisted**: For complex fixes requiring semantic understanding.
   Uses AgentHandler to generate fixes via LLM.

Configuration:
    AUTO_APPLY_FORMAT_FIXES (env var):
        - "true" (default): Format fixes bypass LLM, applied directly
        - "false": Format fixes go through LLM for review

    Rationale for auto-apply default:
        Format changes are idempotent and safe. Ruff format produces
        deterministic output that matches the project's style configuration.
        There is no semantic risk in applying format changes automatically,
        and doing so significantly reduces LLM costs and latency.

Usage:
    from orchestrator.fix_planner import FixPlanner

    planner = FixPlanner()
    result = planner.create_fix_plan(signal_group)

    if result.success:
        # result.fix_plan is ready for PRGenerator
        pr_result = pr_generator.create_pr(result.fix_plan)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Optional dotenv support for local development
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional, env vars can be set directly

from agents.agent_handler import (
    AgentHandler,
    AgentResult,
    CodeEdit,
    EditType,
    FileEdit,
    FixPlan,
    Position,
    Span,
)
from orchestrator.context_builder import ContextBuilder
from orchestrator.prioritizer import SignalGroup
from signals.models import FixSignal, SignalType


# =============================================================================
# Configuration
# =============================================================================

def _get_auto_apply_format_fixes() -> bool:
    """
    Check if format fixes should be auto-applied without LLM review.

    Environment variable: AUTO_APPLY_FORMAT_FIXES
        - "true", "1", "yes" (default): Auto-apply format fixes
        - "false", "0", "no": Send format fixes through LLM

    Default is True because:
        - Format changes are idempotent (running twice gives same result)
        - Format changes are safe (no semantic changes to code)
        - Ruff format output is deterministic and well-tested
        - Bypassing LLM saves cost and reduces latency
        - Format rules are configured in pyproject.toml, reflecting team preferences
    """
    value = os.getenv("AUTO_APPLY_FORMAT_FIXES", "true").lower().strip()
    return value in ("true", "1", "yes", "")


# Module-level config (evaluated once at import time)
AUTO_APPLY_FORMAT_FIXES = _get_auto_apply_format_fixes()


def _should_debug_llm() -> bool:
    """
    Check if context should be dumped for debugging.

    Environment variable: DEBUG_LLM_CONTEXT
        - "true", "1", "yes": Enable context debugging
        - "false", "0", "no" (default): Disabled
    """
    value = os.getenv("DEBUG_LLM", "false").lower().strip()
    return value in ("true", "1", "yes")


def _dump_llm_data_to_file(
    context: dict[str, Any],
    group: SignalGroup,
    result: AgentResult,
    prompts: dict[str, str] | None = None,
    output_dir: str | Path = "scripts/debug/llm-contexts",
) -> None:
    """
    Dump LLM context and prompts to a JSON file for debugging.

    Creates one file per signal group with a timestamp and group identifier.
    Includes both the context data AND the exact prompts sent to the LLM.

    Args:
        context: The context dictionary being sent to the LLM
        group: The SignalGroup being processed
        prompts: Dict with 'system_prompt' and 'user_prompt' (optional)
        output_dir: Directory to save context files (created if doesn't exist)
    """
    try:
        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp and group info
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        tool_id = group.tool_id.replace("/", "-")  # Sanitize tool_id for filename
        signal_type = group.signal_type.value
        num_signals = len(group.signals)

        filename = f"context_{tool_id}_{signal_type}_{num_signals}signals_{timestamp}.json"
        filepath = output_path / filename

        # Add metadata to context for better debugging
        debug_output = {
            "_debug_metadata": {
                "timestamp": timestamp,
                "tool_id": group.tool_id,
                "signal_type": signal_type,
                "num_signals": num_signals,
                "signal_files": list(set(s.file_path for s in group.signals if s.file_path)),
            },
            "context": context,
        }

        # Add prompts if provided
        if prompts:
            debug_output["prompts"] = {
                "system_prompt": prompts.get("system_prompt", ""),
                "user_prompt": prompts.get("user_prompt", ""),
            }
            # Also add prompt stats for quick reference
            debug_output["_debug_metadata"]["system_prompt_length"] = len(prompts.get("system_prompt", ""))
            debug_output["_debug_metadata"]["user_prompt_length"] = len(prompts.get("user_prompt", ""))

        # Write to file
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(debug_output, f, indent=2, default=str)
            if result.success:
                f.write("========== LLM RESULT FROM ABOVE CONTEXT ===========")
                f.write(f"LLM Content:\n{result.llm_response.content}")
            else:
                f.write(f"LLM Error:\n{result.error}")


        print(f"[DEBUG] Context and prompts dumped to: {filepath}")

    except Exception as e:
        # Don't fail the entire process if debug dumping fails
        print(f"[WARNING] Failed to dump context for debugging: {e}")


# =============================================================================
# Result Types
# =============================================================================

@dataclass
class PlannerResult:
    """Result from fix planner."""
    success: bool
    fix_plan: Optional[FixPlan] = None
    error: Optional[str] = None
    used_llm: bool = False  # True if LLM was used, False if direct conversion
    agent_result: Optional[AgentResult] = None  # Present if LLM was used


# =============================================================================
# Fix Planner
# =============================================================================

class FixPlanner:
    """
    Converts SignalGroups into executable FixPlans.

    Routing logic:
        - FORMAT signals with AUTO_APPLY_FORMAT_FIXES=true: Direct conversion
        - FORMAT signals with AUTO_APPLY_FORMAT_FIXES=false: LLM-assisted
        - All other signals: LLM-assisted

    Direct conversion:
        Extracts edits from FixSignal.fix and converts them to FixPlan format.
        This is fast, deterministic, and free (no LLM calls).

    LLM-assisted:
        Uses ContextBuilder to gather code context, then AgentHandler to
        generate fixes via LLM. More expensive but handles complex cases.
    """

    def __init__(
        self,
        *,
        llm_provider: str = "openai",
        repo_root: str | None = None,
        auto_apply_format: Optional[bool] = None,
    ) -> None:
        """
        Initialize the fix planner.

        Args:
            llm_provider: LLM provider for agent-assisted fixes
            repo_root: Repository root for context building
            auto_apply_format: Override AUTO_APPLY_FORMAT_FIXES env var.
                               If None, uses environment variable.
        """
        self._llm_provider = llm_provider
        self._repo_root = repo_root
        self._auto_apply_format = (
            auto_apply_format if auto_apply_format is not None
            else AUTO_APPLY_FORMAT_FIXES
        )

        # Lazy-init these to avoid unnecessary setup
        self._agent_handler: Optional[AgentHandler] = None
        self._context_builder: Optional[ContextBuilder] = None

    @property
    def auto_apply_format(self) -> bool:
        """Whether format fixes are auto-applied without LLM."""
        return self._auto_apply_format

    def create_fix_plan(self, group: SignalGroup) -> PlannerResult:
        """
        Create a FixPlan from a SignalGroup.

        Routes to direct conversion or LLM based on signal type and config.

        Args:
            group: SignalGroup containing signals to fix

        Returns:
            PlannerResult with FixPlan or error information
        """
        if not group.signals:
            return PlannerResult(
                success=False,
                error="Empty signal group",
            )

        # Route based on signal type and configuration
        if group.signal_type == SignalType.FORMAT and self._auto_apply_format:
            return self._create_direct_fix_plan(group)
        else:
            return self._create_llm_fix_plan(group)

    def _create_direct_fix_plan(self, group: SignalGroup) -> PlannerResult:
        """
        Create FixPlan directly from signal edits (no LLM).

        Used for FORMAT signals when AUTO_APPLY_FORMAT_FIXES=true.
        Extracts edits from FixSignal.fix and converts to FixPlan format.

        This approach is:
            - Fast: No network calls, pure Python conversion
            - Free: No LLM API costs
            - Deterministic: Same input always produces same output
            - Safe: Format changes don't alter code semantics
        """
        try:
            file_edits: dict[str, FileEdit] = {}

            for signal in group.signals:
                if signal.fix is None:
                    continue

                file_path = signal.file_path

                # Get or create FileEdit for this file
                if file_path not in file_edits:
                    file_edits[file_path] = FileEdit(
                        file_path=file_path,
                        edits=[],
                        reasoning=f"Auto-applied format fixes from {group.tool_id}",
                    )

                # Convert signal edits to CodeEdit format
                for text_edit in signal.fix.edits:
                    code_edit = CodeEdit(
                        edit_type=EditType.REPLACE,
                        span=Span(
                            start=Position(
                                row=text_edit.span.start.row,
                                column=text_edit.span.start.column,
                            ),
                            end=Position(
                                row=text_edit.span.end.row,
                                column=text_edit.span.end.column,
                            ),
                        ),
                        content=text_edit.content,
                        description=signal.fix.message or "Apply formatting",
                    )
                    file_edits[file_path].edits.append(code_edit)

            if not file_edits:
                return PlannerResult(
                    success=False,
                    error="No edits found in signal fixes",
                )

            fix_plan = FixPlan(
                group_tool_id=group.tool_id,
                group_signal_type=group.signal_type.value,
                file_edits=list(file_edits.values()),
                summary=f"Auto-applied {len(group.signals)} format fix(es) across {len(file_edits)} file(s)",
                warnings=[],
                confidence=1.0,  # Format fixes are always high confidence
            )

            return PlannerResult(
                success=True,
                fix_plan=fix_plan,
                used_llm=False,
            )

        except Exception as e:
            return PlannerResult(
                success=False,
                error=f"Failed to create direct fix plan: {e}",
            )

    def _create_llm_fix_plan(self, group: SignalGroup) -> PlannerResult:
        """
        Create FixPlan using LLM via AgentHandler.

        Used for:
            - Non-FORMAT signals (lint, type_check, security)
            - FORMAT signals when AUTO_APPLY_FORMAT_FIXES=false

        This approach:
            - Builds code context around each signal
            - Sends context to LLM for fix generation
            - Parses LLM response into structured FixPlan
        """
        try:
            # Lazy init agent handler and context builder
            if self._agent_handler is None:
                self._agent_handler = AgentHandler(provider=self._llm_provider)

            if self._context_builder is None:
                self._context_builder = ContextBuilder(repo_root=self._repo_root)

            # Build context for the signal group
            context = self._context_builder.build_group_context(group)

            # Generate fix plan via LLM
            agent_result = self._agent_handler.generate_fix_plan(context)

            # Debug: dump context and prompts to file if enabled
            if _should_debug_llm():
                # Get the exact prompts that will be sent to LLM
                prompts = self._agent_handler.get_prompts_for_context(context)
                _dump_llm_data_to_file(context, group, agent_result, prompts=prompts)

            if not agent_result.success:
                return PlannerResult(
                    success=False,
                    error=agent_result.error,
                    used_llm=True,
                    agent_result=agent_result,
                )

            return PlannerResult(
                success=True,
                fix_plan=agent_result.fix_plan,
                used_llm=True,
                agent_result=agent_result,
            )

        except Exception as e:
            return PlannerResult(
                success=False,
                error=f"Failed to create LLM fix plan: {e}",
                used_llm=True,
            )


# =============================================================================
# Convenience Functions
# =============================================================================

def create_fix_plan(
    group: SignalGroup,
    *,
    llm_provider: str = "openai",
    repo_root: str | None = None,
    auto_apply_format: Optional[bool] = None,
) -> PlannerResult:
    """
    Convenience function to create a fix plan from a signal group.

    Args:
        group: SignalGroup to create fix plan for
        llm_provider: LLM provider for agent-assisted fixes
        repo_root: Repository root for context building
        auto_apply_format: Override AUTO_APPLY_FORMAT_FIXES env var

    Returns:
        PlannerResult with fix_plan or error
    """
    planner = FixPlanner(
        llm_provider=llm_provider,
        repo_root=repo_root,
        auto_apply_format=auto_apply_format,
    )
    return planner.create_fix_plan(group)


def create_format_fix_plan_direct(signals: list[FixSignal], tool_id: str = "ruff-format") -> PlannerResult:
    """
    Create a FixPlan directly from FORMAT signals without LLM.

    This is a lower-level function for when you have raw signals
    and want to bypass the SignalGroup abstraction.

    Args:
        signals: List of FORMAT FixSignals with fix.edits
        tool_id: Tool identifier for the fix plan

    Returns:
        PlannerResult with fix_plan or error
    """
    group = SignalGroup(
        tool_id=tool_id,
        signal_type=SignalType.FORMAT,
        signals=signals,
    )

    planner = FixPlanner(auto_apply_format=True)
    return planner.create_fix_plan(group)

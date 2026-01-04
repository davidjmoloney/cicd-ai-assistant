# agents/agent_handler.py
"""
Agent Handler for generating code fixes via LLM.

This module handles:
  - Taking context from ContextBuilder.build_group_context()
  - Sending it to an LLM provider
  - Parsing the response into a structured FixPlan

The FixPlan output is designed to be applied later by code editing tools
or passed to a PR generation function.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from agents.llm_provider import (
    LLMError,
    LLMProvider,
    LLMResponse,
    get_provider,
)


# ============================================================================
# Fix Plan Models (structured output)
# ============================================================================

class EditType(str, Enum):
    """Type of edit to apply."""
    REPLACE = "replace"      # Replace text at span
    INSERT = "insert"        # Insert text at position
    DELETE = "delete"        # Delete text at span


@dataclass
class Position:
    """Position in a file (1-based row, 0-based column)."""
    row: int
    column: int


@dataclass
class Span:
    """A range in a file."""
    start: Position
    end: Position


@dataclass
class CodeEdit:
    """
    A single code edit operation.

    This matches the structure used by Ruff and other tools,
    making it easy to integrate with existing edit application code.
    """
    edit_type: EditType
    span: Span
    content: str  # New content (empty string for DELETE)
    description: str  # Human-readable description of the edit


@dataclass
class FileEdit:
    """
    All edits for a single file.

    Edits are ordered by position (top to bottom) and should be
    applied in reverse order to preserve line numbers.
    """
    file_path: str
    edits: list[CodeEdit] = field(default_factory=list)
    reasoning: str = ""  # LLM's reasoning for these edits


@dataclass
class FixPlan:
    """
    Complete fix plan for a signal group.

    This is the structured output from the agent, ready to be
    applied by code editing tools or passed to PR generation.
    """
    group_tool_id: str
    group_signal_type: str
    file_edits: list[FileEdit] = field(default_factory=list)
    summary: str = ""  # Overall summary of fixes
    warnings: list[str] = field(default_factory=list)  # Any warnings/caveats
    confidence: float = 1.0  # 0.0-1.0 confidence in the fix

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "group_tool_id": self.group_tool_id,
            "group_signal_type": self.group_signal_type,
            "file_edits": [
                {
                    "file_path": fe.file_path,
                    "reasoning": fe.reasoning,
                    "edits": [
                        {
                            "edit_type": e.edit_type.value,
                            "span": {
                                "start": {"row": e.span.start.row, "column": e.span.start.column},
                                "end": {"row": e.span.end.row, "column": e.span.end.column},
                            },
                            "content": e.content,
                            "description": e.description,
                        }
                        for e in fe.edits
                    ],
                }
                for fe in self.file_edits
            ],
            "summary": self.summary,
            "warnings": self.warnings,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FixPlan":
        """Create FixPlan from dictionary."""
        file_edits = []
        for fe_data in data.get("file_edits", []):
            edits = []
            for e_data in fe_data.get("edits", []):
                span_data = e_data.get("span", {})
                start = span_data.get("start", {})
                end = span_data.get("end", {})
                edits.append(
                    CodeEdit(
                        edit_type=EditType(e_data.get("edit_type", "replace")),
                        span=Span(
                            start=Position(row=start.get("row", 1), column=start.get("column", 0)),
                            end=Position(row=end.get("row", 1), column=end.get("column", 0)),
                        ),
                        content=e_data.get("content", ""),
                        description=e_data.get("description", ""),
                    )
                )
            file_edits.append(
                FileEdit(
                    file_path=fe_data.get("file_path", ""),
                    edits=edits,
                    reasoning=fe_data.get("reasoning", ""),
                )
            )

        return cls(
            group_tool_id=data.get("group_tool_id", ""),
            group_signal_type=data.get("group_signal_type", ""),
            file_edits=file_edits,
            summary=data.get("summary", ""),
            warnings=data.get("warnings", []),
            confidence=data.get("confidence", 1.0),
        )


@dataclass
class AgentResult:
    """Result from agent handler."""
    success: bool
    fix_plan: Optional[FixPlan] = None
    error: Optional[str] = None
    llm_response: Optional[LLMResponse] = None
    llm_error: Optional[LLMError] = None


# ============================================================================
# System prompt for fix generation
# ============================================================================

FIX_GENERATION_SYSTEM_PROMPT = """You are an expert code repair agent. Your task is to analyze linting/type/security signals and generate precise code fixes.

IMPORTANT: You must respond with valid JSON only. No markdown, no explanations outside the JSON.

Given context about code issues (signals), you will:
1. Analyze each signal and its surrounding code context
2. Determine the correct fix
3. Output a structured fix plan as JSON

The fix plan JSON schema:
{
  "summary": "Brief description of all fixes",
  "confidence": 0.0-1.0,
  "warnings": ["any caveats or things to check"],
  "file_edits": [
    {
      "file_path": "path/to/file.py",
      "reasoning": "Why these edits fix the issue",
      "edits": [
        {
          "edit_type": "replace|insert|delete",
          "span": {
            "start": {"row": 1, "column": 0},
            "end": {"row": 1, "column": 10}
          },
          "content": "new code to insert (empty string for delete)",
          "description": "What this edit does"
        }
      ]
    }
  ]
}

Guidelines:
- Row numbers are 1-based (first line is row 1)
- Column numbers are 0-based (first character is column 0)
- For REPLACE: span covers text to replace, content is the replacement
- For INSERT: span.start = span.end = insertion point, content is text to insert
- For DELETE: span covers text to delete, content should be empty string
- Order edits top-to-bottom within each file
- If a tool-provided fix exists and is marked "safe", prefer using it
- If you cannot determine a safe fix, set confidence < 0.5 and add a warning
- Be precise with line/column numbers - incorrect positions break the fix

When the signal includes fix_context with existing tool edits:
- If applicability is "safe", use those edits directly
- If applicability is "unsafe", review carefully and adjust if needed
- Always verify the edit positions match the actual code shown in code_context
"""


# ============================================================================
# Agent Handler
# ============================================================================

class AgentHandler:
    """
    Handles LLM-based code fix generation.

    Usage:
        handler = AgentHandler(provider="openai")
        context = context_builder.build_group_context(signal_group)
        result = handler.generate_fix_plan(context)

        if result.success:
            # Apply result.fix_plan to codebase
            pass
    """

    def __init__(
        self,
        provider: str | LLMProvider = "openai",
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        system_prompt: Optional[str] = None,
    ) -> None:
        """
        Initialize the agent handler.

        Args:
            provider: LLM provider name ('openai', 'anthropic') or LLMProvider instance
            temperature: Sampling temperature (0.0 for deterministic)
            max_tokens: Maximum tokens in response
            system_prompt: Custom system prompt (uses default if None)
        """
        if isinstance(provider, str):
            self._provider = get_provider(provider)
        else:
            self._provider = provider

        self._temperature = temperature
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt or FIX_GENERATION_SYSTEM_PROMPT

    @property
    def provider(self) -> LLMProvider:
        """Get the current LLM provider."""
        return self._provider

    def set_provider(self, provider: str | LLMProvider) -> None:
        """
        Change the LLM provider.

        Args:
            provider: Provider name or LLMProvider instance
        """
        if isinstance(provider, str):
            self._provider = get_provider(provider)
        else:
            self._provider = provider

    def generate_fix_plan(
        self,
        context: dict[str, Any],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AgentResult:
        """
        Generate a fix plan from signal group context.

        Args:
            context: Output from ContextBuilder.build_group_context()
            temperature: Override default temperature
            max_tokens: Override default max_tokens

        Returns:
            AgentResult with success status and fix_plan or error
        """
        if not self._provider.is_configured():
            return AgentResult(
                success=False,
                error=f"Provider {self._provider.provider_name} is not configured. Set API key.",
            )

        # Build user prompt from context
        user_prompt = self._build_user_prompt(context)

        # Call LLM
        response = self._provider.generate(
            system_prompt=self._system_prompt,
            user_prompt=user_prompt,
            temperature=temperature if temperature is not None else self._temperature,
            max_tokens=max_tokens if max_tokens is not None else self._max_tokens,
        )

        if isinstance(response, LLMError):
            return AgentResult(
                success=False,
                error=f"LLM error ({response.error_type}): {response.message}",
                llm_error=response,
            )

        # Parse response into FixPlan
        try:
            fix_plan = self._parse_response(response.content, context)
            return AgentResult(
                success=True,
                fix_plan=fix_plan,
                llm_response=response,
            )
        except Exception as e:
            return AgentResult(
                success=False,
                error=f"Failed to parse LLM response: {e}",
                llm_response=response,
            )

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        """Build the user prompt from context."""
        return f"Generate a fix plan for the following signals:\n\n{json.dumps(context, indent=2)}"

    def _parse_response(self, content: str, context: dict[str, Any]) -> FixPlan:
        """Parse LLM response into FixPlan."""
        # Try to extract JSON from response
        # Handle case where LLM wraps in markdown code block
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Assume entire content is JSON
            json_str = content.strip()

        data = json.loads(json_str)

        # Add group info from context
        group_info = context.get("group", {})
        data["group_tool_id"] = group_info.get("tool_id", "unknown")
        data["group_signal_type"] = group_info.get("signal_type", "unknown")

        return FixPlan.from_dict(data)


# ============================================================================
# Convenience functions
# ============================================================================

def generate_fix(
    context: dict[str, Any],
    *,
    provider: str = "openai",
    temperature: float = 0.0,
) -> AgentResult:
    """
    Convenience function to generate a fix plan.

    Args:
        context: Output from ContextBuilder.build_group_context()
        provider: LLM provider name ('openai', 'anthropic')
        temperature: Sampling temperature

    Returns:
        AgentResult with fix_plan or error
    """
    handler = AgentHandler(provider=provider, temperature=temperature)
    return handler.generate_fix_plan(context)

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
from agents.tool_prompts import get_system_prompt


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
# NOTE: System prompts are now in agents/tool_prompts.py
# This allows tool-specific guidance (mypy, ruff, pydocstyle etc.)


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
            system_prompt: Custom system prompt override (if None, uses tool-specific prompts)
        """
        if isinstance(provider, str):
            self._provider = get_provider(provider)
        else:
            self._provider = provider

        self._temperature = temperature
        self._max_tokens = max_tokens
        self._system_prompt_override = system_prompt  # Store override, but use tool-specific by default

    @property
    def provider(self) -> LLMProvider:
        """Get the current LLM provider."""
        return self._provider

    def get_prompt_for_tool(self, tool_id: str | None = None) -> str:
        """
        Get the system prompt that would be used for a given tool.

        Useful for debugging and testing.

        Args:
            tool_id: Tool identifier (e.g., "mypy", "ruff", "pydocstyle")

        Returns:
            Complete system prompt with tool-specific guidance
        """
        return self._system_prompt_override or get_system_prompt(tool_id)

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

    def get_prompts_for_context(self, context: dict[str, Any]) -> dict[str, str]:
        """
        Get the exact prompts that would be sent to the LLM for debugging.

        This method returns both the system prompt and user prompt without
        actually calling the LLM. Useful for debugging and understanding
        exactly what the LLM receives.

        Args:
            context: Output from ContextBuilder.build_group_context()

        Returns:
            Dict with 'system_prompt' and 'user_prompt' keys
        """
        tool_id = context.get("group", {}).get("tool_id")
        system_prompt = self._system_prompt_override or get_system_prompt(tool_id)
        user_prompt = self._build_user_prompt(context)

        return {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }

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

        # Extract tool_id from context to get tool-specific prompt
        tool_id = context.get("group", {}).get("tool_id")

        # Use override if provided, otherwise get tool-specific prompt
        system_prompt = self._system_prompt_override or get_system_prompt(tool_id)

        # Build user prompt from context
        user_prompt = self._build_user_prompt(context)

        # Call LLM with tool-specific guidance
        response = self._provider.generate(
            system_prompt=system_prompt,
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
        """Build the user prompt from context with clear snippet presentation."""
        parts = []

        group_info = context.get("group", {})
        parts.append(f"Tool: {group_info.get('tool_id', 'unknown')}")
        parts.append(f"Signal Type: {group_info.get('signal_type', 'unknown')}")
        parts.append(f"Number of Signals: {group_info.get('group_size', 0)}")
        parts.append("")

        for idx, signal_data in enumerate(context.get("signals", []), 1):
            signal = signal_data.get("signal", {})
            edit_snippet = signal_data.get("edit_snippet")
            code_context = signal_data.get("code_context", {})

            parts.append(f"{'='*60}")
            parts.append(f"SIGNAL {idx}")
            parts.append(f"{'='*60}")
            parts.append("")

            # Error information
            parts.append("## Error Information")
            parts.append(f"- File: {signal.get('file_path', 'unknown')}")
            parts.append(f"- Message: {signal.get('message', 'No message')}")
            parts.append(f"- Rule Code: {signal.get('rule_code', 'N/A')}")
            parts.append(f"- Severity: {signal.get('severity', 'unknown')}")
            if signal.get('span'):
                span = signal['span']
                parts.append(f"- Location: Line {span['start']['row']}, Column {span['start']['column']}")
            parts.append("")

            # Edit snippet - this is what they need to fix and return
            if edit_snippet:
                parts.append("## Edit Snippet (FIX AND RETURN THIS)")
                parts.append(f"Lines {edit_snippet['start_row']}-{edit_snippet['end_row']} "
                           f"(error on line {edit_snippet['error_line_in_snippet']} of {edit_snippet['snippet_length']})")
                parts.append("```python")
                parts.append(edit_snippet['text'])
                parts.append("```")
                parts.append("")

            # Context window - for understanding only
            window = code_context.get("window")
            if window:
                parts.append("## Context Window (for understanding, DO NOT return)")
                parts.append(f"Lines {window['start_row']}-{window['end_row']}")
                parts.append("```python")
                parts.append(window['text'])
                parts.append("```")
                parts.append("")

            # Imports context
            imports = code_context.get("imports")
            if imports:
                parts.append("## Imports")
                parts.append("```python")
                parts.append(imports['text'])
                parts.append("```")
                parts.append("")

            # Enclosing function context
            enclosing = code_context.get("enclosing_function")
            if enclosing:
                parts.append("## Enclosing Function")
                parts.append(f"Lines {enclosing['start_row']}-{enclosing['end_row']}")
                parts.append("```python")
                parts.append(enclosing['text'])
                parts.append("```")
                parts.append("")

            # Additional context blocks
            class_def = code_context.get("class_definition")
            if class_def:
                parts.append("## Class Definition")
                parts.append(f"Lines {class_def['start_row']}-{class_def['end_row']}")
                parts.append("```python")
                parts.append(class_def['text'])
                parts.append("```")
                parts.append("")

            type_aliases = code_context.get("type_aliases")
            if type_aliases:
                parts.append("## Type Aliases")
                parts.append(f"Lines {type_aliases['start_row']}-{type_aliases['end_row']}")
                parts.append("```python")
                parts.append(type_aliases['text'])
                parts.append("```")
                parts.append("")

            related_func = code_context.get("related_function")
            if related_func:
                parts.append("## Related Function Signature")
                parts.append(f"Lines {related_func['start_row']}-{related_func['end_row']}")
                parts.append("```python")
                parts.append(related_func['text'])
                parts.append("```")
                parts.append("")

            module_constants = code_context.get("module_constants")
            if module_constants:
                parts.append("## Module Constants")
                parts.append(f"Lines {module_constants['start_row']}-{module_constants['end_row']}")
                parts.append("```python")
                parts.append(module_constants['text'])
                parts.append("```")
                parts.append("")

            parts.append("")

        parts.append("Please provide fixes for the above signals using the specified response format.")

        return "\n".join(parts)
    

    def _restore_base_indent(self, code: str, base_indent: str) -> str:
        lines = code.splitlines(keepends=True)
        out = []
        for line in lines:
            if line.strip():
                out.append(base_indent + line)
            else:
                out.append(line)
        return "".join(out)


    def _parse_response(self, content: str, context: dict[str, Any]) -> FixPlan:
        """Parse LLM response with delimited snippets into FixPlan."""
        # Parse the new format: ===== FIX FOR: <path> ===== ... ===== END FIX =====
        fix_pattern = re.compile(
            r"={5,}\s*FIX FOR:\s*(.+?)\s*={5,}\s*"
            r"CONFIDENCE:\s*([\d.]+)\s*"
            r"REASONING:\s*([\s\S]+?)\s*"
            r"```FIXED_CODE[ \t]*\r?\n([\s\S]*?)\r?\n```[ \t]*\s*"
            r"WARNINGS:\s*([\s\S]+?)\s*"
            r"={5,}\s*END FIX\s*={5,}",
            re.IGNORECASE
        )

        matches = fix_pattern.findall(content)

        if not matches:
            raise ValueError(
                "Could not parse LLM response. Expected format with "
                "===== FIX FOR: <path> ===== ... ```FIXED_CODE ... ``` ... ===== END FIX ====="
            )

        # Build file edits from parsed fixes
        file_edits: list[FileEdit] = []
        all_warnings: list[str] = []
        total_confidence = 0.0

        # Get signals from context for position information
        signals = context.get("signals", [])

        for idx, match in enumerate(matches):
            file_path, confidence_str, reasoning, fixed_code, warnings_str = match
            file_path = file_path.strip()

            try:
                confidence = float(confidence_str.strip())
            except ValueError:
                confidence = 0.5

            total_confidence += confidence

            # Parse warnings
            warnings_str = warnings_str.strip()
            if warnings_str.lower() != "none" and warnings_str:
                all_warnings.append(f"{file_path}: {warnings_str}")

            # Match fix to signal by index
            # LLM receives signals as SIGNAL 1, SIGNAL 2, etc. and responds in same order
            # So fix at index 0 corresponds to signal at index 0, etc.
            if idx >= len(signals):
                all_warnings.append(
                    f"Fix index {idx} exceeds number of signals ({len(signals)}), skipping"
                )
                continue

            sig_data = signals[idx]
            edit_snippet = sig_data.get("edit_snippet")

            if not edit_snippet:
                sig_file = sig_data.get("signal", {}).get("file_path", "unknown")
                all_warnings.append(f"No edit snippet available for signal {idx} ({sig_file}), skipping")
                continue

            # Build the edit using snippet positions
            # Use line-based replacement: start at column 1, end at large column on last line
            # This effectively replaces entire lines from start_row to end_row inclusive
            start_row = edit_snippet["start_row"]
            end_row = edit_snippet["end_row"]
            base_indent = edit_snippet.get("base_indent", "")

            # Re-apply base indentation to all lines in the fixed code
            fixed_code = self._restore_base_indent(fixed_code, base_indent)

            # Ensure fixed_code ends with newline for clean replacement
            # fixed_code = fixed_code.rstrip('\n') + '\n'

            code_edit = CodeEdit(
                edit_type=EditType.REPLACE,
                span=Span(
                    start=Position(row=start_row, column=1),
                    # Use large column number to capture entire last line
                    # _apply_edit will take suffix as empty since we're past line end
                    end=Position(row=end_row, column=99999),
                ),
                content=fixed_code,
                description=reasoning.strip(),
            )

            file_edits.append(FileEdit(
                file_path=file_path,
                edits=[code_edit],
                reasoning=reasoning.strip(),
            ))

        # Calculate average confidence
        avg_confidence = total_confidence / len(matches) if matches else 0.5

        # Build summary
        group_info = context.get("group", {})
        summary = f"Fixed {len(file_edits)} file(s) for {group_info.get('tool_id', 'unknown')} signals"

        return FixPlan(
            group_tool_id=group_info.get("tool_id", "unknown"),
            group_signal_type=group_info.get("signal_type", "unknown"),
            file_edits=file_edits,
            summary=summary,
            warnings=all_warnings,
            confidence=avg_confidence,
        )

    def _validate_fix_plan(self, fix_plan: FixPlan) -> list[str]:
        """
        Validate fix plan for common issues.

        Returns list of warning messages for issues found.
        """
        warnings = []

        for file_edit in fix_plan.file_edits:
            for edit in file_edit.edits:
                # Check for invalid spans (end before start)
                if edit.span.end.row < edit.span.start.row:
                    warnings.append(
                        f"Invalid span in {file_edit.file_path}: end row {edit.span.end.row} "
                        f"< start row {edit.span.start.row}"
                    )

                # Check for empty content on REPLACE
                if edit.edit_type == EditType.REPLACE and not edit.content.strip():
                    warnings.append(
                        f"Empty content for REPLACE in {file_edit.file_path} at "
                        f"rows {edit.span.start.row}-{edit.span.end.row}. "
                        f"This will delete the lines. Was this intended?"
                    )

        return warnings


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

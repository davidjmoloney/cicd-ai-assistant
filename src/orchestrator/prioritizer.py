# orchestrator/prioritizer.py
"""
Signal prioritization and grouping for the CI/CD AI assistant.

This module handles:
  - Prioritizing signals by type and severity
  - Grouping signals for efficient batch processing
  - Special handling for FORMAT signals (file-based grouping)

Priority order (highest to lowest):
  SECURITY > TYPE_CHECK > LINT > FORMAT

FORMAT signals are grouped differently:
  - One SignalGroup per file (not chunked by max_group_size)
  - This enables efficient "apply all format fixes" mode
  - Format changes within a file are often interdependent
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from signals.models import FixSignal, SignalType


# ----------------------------
# Priority constants
# ----------------------------

# Signal type priority order (lower number = higher priority)
# FORMAT is always processed last as it's cosmetic and safe
SIGNAL_TYPE_PRIORITY: dict[SignalType, int] = {
    SignalType.SECURITY: 0,     # Security issues first
    SignalType.TYPE_CHECK: 1,   # Type errors second
    SignalType.LINT: 2,         # Lint issues third
    SignalType.FORMAT: 3,       # Format issues last (cosmetic, always safe)
}


# ----------------------------
# Output type
# ----------------------------

@dataclass(frozen=True)
class SignalGroup:
    """
    A batch of signals to be passed to an agent.

    v1 rules (simple):
      - tool-homogeneous groups (ruff separate from mypy/bandit)
      - preserve original order within each tool
      - max 3 signals per group

    Special handling for FORMAT signals:
      - Grouped by file, not by max_group_size
      - Each SignalGroup contains all format changes for a single file
      - This enables efficient batch application without LLM review

    Rationale for file-based FORMAT grouping:
      - Format changes within a file are interdependent (line numbers shift)
      - Applying all format changes at once is more efficient
      - Format is idempotent and safe, so batching has no risk
    """
    tool_id: str
    signal_type: SignalType
    signals: list[FixSignal]


# ----------------------------
# Tool resolution
# ----------------------------

def default_tool_resolver(sig: FixSignal) -> str:
    """
    v1 heuristic resolver (because only Ruff exists right now).

    FUTURE (preferred):
      - Add `tool_id: str` onto FixSignal and return it directly:
          return sig.tool_id
    """
    # Handle FORMAT signals from ruff format
    if sig.signal_type == SignalType.FORMAT:
        return "ruff-format"

    if sig.docs_url and "docs.astral.sh/ruff" in sig.docs_url:
        return "ruff"
    if sig.fix is not None:
        return "ruff"
    return "unknown"


# ----------------------------
# Simple prioritizer (v1)
# ----------------------------

class Prioritizer:
    """
    v1 prioritizer: keep things simple and stable.

    Groups signals for efficient processing:
      - Non-FORMAT signals: chunked by max_group_size
      - FORMAT signals: grouped by file (one group per file)

    Priority ordering:
      - Groups are sorted by signal type priority (SECURITY first, FORMAT last)
      - Within each type, original encounter order is preserved

    Rationale for FORMAT file-based grouping:
      - Format changes within a file are interdependent (applying one may
        shift line numbers for others)
      - Grouping by file enables atomic "apply all" operations
      - Format is idempotent and safe, so larger groups have no risk
      - This also enables bypassing LLM review for format fixes
    """

    def __init__(
        self,
        *,
        max_group_size: int = 3,
        tool_resolver: Callable[[FixSignal], str] = default_tool_resolver,
    ) -> None:
        if max_group_size < 1:
            raise ValueError("max_group_size must be >= 1")
        self._max_group_size = max_group_size
        self._tool_resolver = tool_resolver

    def prioritize(self, signals: list[FixSignal]) -> list[SignalGroup]:
        """
        Pack signals into groups with priority ordering.

        Steps:
          1) Separate signals by type (FORMAT vs others)
          2) For non-FORMAT: bucket by tool, chunk by max_group_size
          3) For FORMAT: group by file (all signals for a file in one group)
          4) Sort all groups by priority (SECURITY > TYPE_CHECK > LINT > FORMAT)
          5) Return ordered groups

        Returns:
            List of SignalGroup ordered by priority (highest first).
            FORMAT groups always appear last.
        """
        if not signals:
            return []

        # Separate FORMAT signals from others
        format_signals: list[FixSignal] = []
        other_signals: list[FixSignal] = []

        for s in signals:
            if s.signal_type == SignalType.FORMAT:
                format_signals.append(s)
            else:
                other_signals.append(s)

        # Process non-FORMAT signals with standard chunking
        other_groups = self._group_by_tool_chunked(other_signals)

        # Process FORMAT signals with file-based grouping
        format_groups = self._group_format_by_file(format_signals)

        # Combine and sort by priority
        all_groups = other_groups + format_groups
        all_groups.sort(key=lambda g: SIGNAL_TYPE_PRIORITY.get(g.signal_type, 99))

        return all_groups

    def _group_by_tool_chunked(self, signals: list[FixSignal]) -> list[SignalGroup]:
        """
        Group signals by tool with max_group_size chunking.

        This is the original v1 behavior for non-FORMAT signals.
        """
        if not signals:
            return []

        # Bucket by tool_id while preserving encounter order
        buckets: dict[str, list[FixSignal]] = {}
        tool_order: list[str] = []

        for s in signals:
            tool_id = self._tool_resolver(s)
            if tool_id not in buckets:
                buckets[tool_id] = []
                tool_order.append(tool_id)
            buckets[tool_id].append(s)

        # Pack each tool bucket in order
        groups: list[SignalGroup] = []
        for tool_id in tool_order:
            bucket = buckets[tool_id]
            for i in range(0, len(bucket), self._max_group_size):
                chunk = bucket[i : i + self._max_group_size]
                groups.append(
                    SignalGroup(
                        tool_id=tool_id,
                        signal_type=_dominant_signal_type(chunk),
                        signals=chunk,
                    )
                )

        return groups

    def _group_format_by_file(self, signals: list[FixSignal]) -> list[SignalGroup]:
        """
        Group FORMAT signals by file path.

        Each SignalGroup contains all format changes for a single file.
        This enables efficient batch application without LLM review.

        Rationale:
          - Format changes within a file are interdependent
          - Applying all format changes atomically avoids line number drift
          - Format is idempotent and safe, so large groups are fine
          - Enables "apply all format fixes" mode to bypass LLM entirely
        """
        if not signals:
            return []

        # Bucket by file path
        by_file: dict[str, list[FixSignal]] = {}
        file_order: list[str] = []

        for s in signals:
            if s.file_path not in by_file:
                by_file[s.file_path] = []
                file_order.append(s.file_path)
            by_file[s.file_path].append(s)

        # Create one group per file
        groups: list[SignalGroup] = []
        for file_path in file_order:
            file_signals = by_file[file_path]
            # All FORMAT signals come from ruff-format
            tool_id = self._tool_resolver(file_signals[0])
            groups.append(
                SignalGroup(
                    tool_id=tool_id,
                    signal_type=SignalType.FORMAT,
                    signals=file_signals,
                )
            )

        return groups


def _dominant_signal_type(signals: Iterable[FixSignal]) -> SignalType:
    """
    v1: pick the first signal's type (stable, preserves order).
    For Ruff v1 this will always be SignalType.LINT anyway.

    FUTURE:
      - enforce same type within a group
      - or pick most common type if mixing is allowed
    """
    # signals is always non-empty in our usage
    return next(iter(signals)).signal_type


# -------------------------------------------------------------------------
# FUTURE: "real" prioritisation hooks (NOT IMPLEMENTED YET)
# -------------------------------------------------------------------------

def prioritize_by_severity_and_location(signals: list[FixSignal]) -> list[FixSignal]:
    """
    FUTURE (pseudocode):
      - sort by severity descending (CRITICAL > HIGH > MEDIUM > LOW)
      - tie-break by:
          - file_path
          - span.start.row, span.start.column (if present)
          - rule_code
      - return sorted signals

    NOTE:
      This should probably happen *within a tool bucket* first,
      then groups are packed from that sorted list.
    """
    raise NotImplementedError


def group_by_file_proximity(signals: list[FixSignal], *, max_group_size: int = 3) -> list[list[FixSignal]]:
    """
    FUTURE (pseudocode):
      - goal: keep groups coherent, ideally same file or adjacent rows
      - steps:
          1) partition by file_path
          2) within each file: sort by row/col
          3) pack into groups of <= max_group_size
          4) interleave files by top severity to avoid ignoring severe issues
    """
    raise NotImplementedError


def compute_group_priority_score(group: list[FixSignal]) -> float:
    """
    FUTURE (pseudocode):
      - score = max severity score in group
      - optionally add:
          - bonus if all in same file (lower context switching)
          - penalty if any fix is UNSAFE
          - bonus if edits exist (deterministic autofix)
    """
    raise NotImplementedError

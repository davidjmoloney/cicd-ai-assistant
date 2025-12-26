# orchestrator/prioritizer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from signals.models import FixSignal, SignalType


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
    It groups in the same order the signals appear in the input list.
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
        Pack signals into groups, preserving original order.

        Steps:
          1) Bucket by tool, but preserve encounter order inside each bucket
          2) Split each bucket into chunks of <= max_group_size
          3) Return groups in deterministic order (by tool_id, then bucket order)

        NOTE: The only "reordering" is separating tools.
              Within a tool bucket, order is preserved.
        """
        if not signals:
            return []

        # 1) Bucket by tool_id while preserving encounter order
        buckets: dict[str, list[FixSignal]] = {}
        tool_order: list[str] = []  # preserves first-seen tool order

        for s in signals:
            tool_id = self._tool_resolver(s)
            if tool_id not in buckets:
                buckets[tool_id] = []
                tool_order.append(tool_id)
            buckets[tool_id].append(s)

        # 2) Pack each tool bucket in order
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

# signals/models.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence


class SignalType(str, Enum):
    """
    Types of CI/CD signals that can be processed.

    Priority order (highest to lowest): SECURITY > TYPE_CHECK > LINT > FORMAT
    FORMAT is always lowest priority as formatting changes are cosmetic and safe.
    """
    LINT = "lint"
    FORMAT = "format"  # Formatting signals (e.g., ruff format) - always lowest priority
    TYPE_CHECK = "type_check"
    SECURITY = "security"
    # Later:
    # UNIT_TEST = "unit_test"
    # COVERAGE = "coverage"
    # INTEGRATION = "integration"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FixApplicability(str, Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Position:
    row: int
    column: int


@dataclass(frozen=True)
class Span:
    start: Position
    end: Position


@dataclass(frozen=True)
class TextEdit:
    """
    Replace text in [start, end] with `content`.

    NOTE: Row/column here are the Ruff-style 1-based line numbers and 0/1-based
    columns depending on tool; treat them as tool-native until you implement an
    editor that understands them.
    """
    span: Span
    content: str


@dataclass(frozen=True)
class Fix:
    """
    A deterministic patch suggestion (e.g., Ruff's JSON `fix.edits[]`).

    If a tool cannot provide deterministic edits (MyPy, many Bandit cases),
    you simply set fix=None and let the agent decide later.
    """
    applicability: FixApplicability
    message: Optional[str]
    edits: Sequence[TextEdit]


@dataclass(frozen=True)
class FixSignal:
    """
    Normalised, tool-agnostic signal.

    Keep this stable. Add tool-specific evidence as separate payloads if needed
    (but for v1 Ruff, we can keep it minimal and rely on Fix + docs_url).
    """
    signal_type: SignalType
    severity: Severity

    file_path: str
    span: Optional[Span]  # None for signals that don't map to a file region.

    rule_code: Optional[str]  # e.g. Ruff "F401"
    message: str
    docs_url: Optional[str]

    fix: Optional[Fix]  # present if tool provides deterministic edits


# -------------------------------------------------------------------------
# PSEUDOCODE PLACEHOLDERS (do NOT implement in v1)
# -------------------------------------------------------------------------

# BanditFixSignal notes:
# - Bandit outputs "issue_severity", "issue_confidence", CWE, code snippet, etc.
# - Usually no deterministic edits. So FixSignal.fix will often be None.
# - You likely store extra evidence in a separate payload object later.
#
# MyPyFixSignal notes:
# - MyPy often outputs file/line/col + message + error code.
# - No deterministic edits, almost always agent/LLM-required.
# - FixSignal.fix will be None; severity mapping needs a policy table.

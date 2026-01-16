# signals/parsers/mypy.py
"""
Parser for MyPy type checker output.

This module provides parsing for:
  - mypy --output=json (newline-delimited JSON format)

The parser converts MyPy output into normalized FixSignal objects
that can be processed by the rest of the pipeline.

MyPy does not provide deterministic fixes, so all signals will have fix=None
and require LLM-assisted fix generation.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from signals.models import (
    FixSignal,
    Position,
    SignalType,
    Span,
)
from signals.policy.path import to_repo_relative
from signals.policy.severity import severity_for_mypy

logger = logging.getLogger(__name__)


def parse_mypy_results(
    raw: str,
    *,
    repo_root: str | None = None,
) -> list[FixSignal]:
    """
    Parse mypy JSON output (newline-delimited JSON) to normalized FixSignals.

    MyPy does not provide deterministic fixes, so FixSignal.fix will always be None.
    These signals require LLM-assisted fix generation.

    Args:
        raw: Raw output from `mypy --output=json`
        repo_root: Optional repository root for path normalization

    Returns:
        List of FixSignal objects with signal_type=TYPE_CHECK

    Example:
        >>> sample = '{"file": "app/config.py", "line": 55, "column": 33, "message": "Argument has incompatible type", "hint": null, "code": "arg-type", "severity": "error"}'
        >>> signals = parse_mypy_results(sample)
        >>> for sig in signals:
        ...     print(f"{sig.file_path}:{sig.span.start.row} [{sig.rule_code}] {sig.message}")
    """
    if not raw or not raw.strip():
        return []

    signals: list[FixSignal] = []

    for line_num, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue

        try:
            entry = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning(
                "Skipping malformed JSON at line %d: %s (error: %s)",
                line_num,
                line[:100],
                e,
            )
            continue

        signal = _parse_mypy_entry(entry, repo_root=repo_root)
        if signal is not None:
            signals.append(signal)

    return signals


def _parse_mypy_entry(
    entry: dict[str, Any],
    *,
    repo_root: str | None = None,
) -> FixSignal | None:
    """
    Convert a single MyPy JSON entry to a FixSignal.

    Args:
        entry: Parsed JSON object from MyPy output
        repo_root: Optional repository root for path normalization

    Returns:
        FixSignal or None if the entry is malformed
    """
    # Required fields
    file_path = entry.get("file")
    line = entry.get("line")
    message = entry.get("message", "")

    # Validate required fields
    if not file_path or line is None:
        logger.warning(
            "Skipping malformed MyPy entry (missing file or line): %s",
            entry,
        )
        return None

    # Optional fields
    column = entry.get("column", 0)
    hint = entry.get("hint")
    error_code = entry.get("code")
    mypy_severity = entry.get("severity", "error")

    # Build message with hint if available
    full_message = message
    if hint:
        full_message = f"{message} (hint: {hint})"

    # Normalize file path
    normalized_path = to_repo_relative(file_path, repo_root)

    # Create span (MyPy provides line and column, but no end position)
    # Use same position for start and end since MyPy doesn't provide range
    position = Position(row=int(line), column=int(column))
    span = Span(start=position, end=position)

    # Determine severity
    severity = severity_for_mypy(mypy_severity, error_code)

    return FixSignal(
        signal_type=SignalType.TYPE_CHECK,
        severity=severity,
        file_path=normalized_path,
        span=span,
        rule_code=error_code,
        message=full_message,
        docs_url=_mypy_docs_url(error_code),
        fix=None,  # MyPy does not provide deterministic fixes
    )


def _mypy_docs_url(error_code: str | None) -> str | None:
    """
    Generate MyPy documentation URL for an error code.

    Args:
        error_code: MyPy error code (e.g., "arg-type", "return-value")

    Returns:
        URL to MyPy documentation or None if no code provided
    """
    if not error_code:
        return None
    # MyPy error codes documentation
    return f"https://mypy.readthedocs.io/en/stable/error_code_list.html#{error_code}"

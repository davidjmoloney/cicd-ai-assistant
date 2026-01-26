# signals/parsers/pydocstyle.py
"""
Parser for pydocstyle docstring checker output.

This module provides parsing for pydocstyle text output format:
  {file}:{line} at {location}:
          {code}: {message}

The parser converts pydocstyle output into normalized FixSignal objects
that can be processed by the rest of the pipeline.

SUPPORTED ERROR CODES:
  - D101: Missing docstring in public class
  - D102: Missing docstring in public method
  - D103: Missing docstring in public function

All other pydocstyle error codes are filtered out and ignored.

Recommended pydocstyle command:
  pydocstyle app/ --select=D101,D102,D103 --match='(?!test_).*\\.py'

Pydocstyle does not provide auto-fixes, so all signals will have fix=None
and require LLM-assisted fix generation or manual review.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from signals.models import (
    FixSignal,
    Position,
    SignalType,
    Span,
)
from signals.policy.path import to_repo_relative
from signals.policy.severity import severity_for_pydocstyle

logger = logging.getLogger(__name__)


def parse_pydocstyle_results(
    raw: str,
    *,
    repo_root: str | None = None,
) -> list[FixSignal]:
    """
    Parse pydocstyle text output to normalized FixSignals.

    Only processes D101, D102, D103 error codes (missing docstrings).
    All other pydocstyle error codes are filtered out.

    Pydocstyle output format:
        {file_path}:{line} at module level:
                {code}: {message}
        {file_path}:{line} in {visibility} {type} `{name}`:
                {code}: {message}

    Examples:
        app/main.py:303 in public class `CORSDebugMiddleware`:
                D101: Missing docstring in public class
        app/main.py:304 in public method `dispatch`:
                D102: Missing docstring in public method
        app/api/routes.py:17 in public function `export_data`:
                D103: Missing docstring in public function

    Args:
        raw: Raw output from pydocstyle command (run with --select=D101,D102,D103)
        repo_root: Optional repository root for path normalization

    Returns:
        List of FixSignal objects with signal_type=DOCSTRING (only D101-D103 codes)
    """
    if not raw or not raw.strip():
        return []

    signals: list[FixSignal] = []
    lines = raw.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i].strip()  # Strip whitespace for consistent parsing

        # Skip empty lines
        if not line:
            i += 1
            continue

        # Skip error message lines (they match pattern: CODE: message)
        # Error lines have format "D101: Message text"
        if re.match(r'^[A-Z]\d+:', line):
            i += 1
            continue

        # Try to parse location line: {file}:{line} ...
        # Need to pass stripped line and check next line
        entry = _parse_pydocstyle_entry(line, lines, i, repo_root=repo_root)
        if entry is not None:
            signals.append(entry)
            # Skip to line after error message
            i += 2
        else:
            i += 1

    return signals


def _parse_pydocstyle_entry(
    location_line: str,
    all_lines: list[str],
    current_index: int,
    *,
    repo_root: str | None = None,
) -> FixSignal | None:
    """
    Parse a single pydocstyle error entry.

    Only processes D101, D102, D103 error codes (missing docstrings).
    Other error codes are filtered out and return None.

    Args:
        location_line: The location line (stripped), e.g., "app/main.py:303 in public class `CORSDebugMiddleware`:"
        all_lines: All lines from the output (not stripped)
        current_index: Index of current location line
        repo_root: Optional repository root for path normalization

    Returns:
        FixSignal if code is D101-D103, None if parsing fails or code is not supported
    """
    # Pattern: {file}:{line} {rest}:
    # location_line is already stripped by caller
    location_match = re.match(r"^(.+?):(\d+)\s+(.+):$", location_line)
    if not location_match:
        return None

    file_path = location_match.group(1)
    line_num = int(location_match.group(2))
    location_info = location_match.group(3)

    # Get the error message from next line (strip it)
    if current_index + 1 >= len(all_lines):
        return None

    error_line = all_lines[current_index + 1].strip()
    if not error_line:
        return None

    # Pattern: {code}: {message}
    error_match = re.match(r"^([A-Z]\d+):\s+(.+)$", error_line)
    if not error_match:
        return None

    code = error_match.group(1)
    message = error_match.group(2)

    # Filter: Only process missing docstring errors (D101-D103)
    # Other pydocstyle codes are not supported in this integration
    SUPPORTED_CODES = {"D101", "D102", "D103"}
    if code not in SUPPORTED_CODES:
        logger.debug(f"Skipping unsupported pydocstyle code {code} at {file_path}:{line_num}")
        return None

    # Parse location info to extract target type and name
    # Pattern 1: "at module level"
    # Pattern 2: "in {visibility} {type} `{name}`"
    target_type = None
    target_name = None

    if location_info == "at module level":
        target_type = "module"
    else:
        # Pattern: "in public class `CORSDebugMiddleware`"
        in_match = re.match(r"in (\w+) (\w+) `(.+?)`", location_info)
        if in_match:
            # visibility = in_match.group(1)  # "public" or "private"
            target_type = in_match.group(2)  # "function", "class", "method"
            target_name = in_match.group(3)

    # Normalize file path
    normalized_path = to_repo_relative(file_path, repo_root)

    # Create span at the error line
    position = Position(row=line_num, column=0)
    span = Span(start=position, end=position)

    # Determine severity
    severity = severity_for_pydocstyle(code)

    return FixSignal(
        signal_type=SignalType.DOCSTRING,
        severity=severity,
        file_path=normalized_path,
        span=span,
        rule_code=code,
        message=message,
        docs_url=_pydocstyle_docs_url(code),
        fix=None,  # Pydocstyle does not provide auto-fixes
    )


def _pydocstyle_docs_url(error_code: str | None) -> str | None:
    """
    Generate pydocstyle documentation URL for an error code.

    Args:
        error_code: Pydocstyle error code (e.g., "D101", "D212")

    Returns:
        URL to pydocstyle documentation or None if no code provided
    """
    if not error_code:
        return None
    return f"http://www.pydocstyle.org/en/stable/error_codes.html#{error_code}"

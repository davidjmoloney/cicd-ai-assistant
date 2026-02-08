# signals/parsers/ruff.py
"""
Parsers for Ruff linter and formatter output.

This module provides parsing functions for:
  - ruff check --output-format=json (lint results)
  - ruff format --diff (format diff output)

The parsers convert tool-specific output into normalized FixSignal objects
that can be processed by the rest of the pipeline.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from signals.models import (
    Fix,
    FixApplicability,
    FixSignal,
    Position,
    Severity,
    SignalType,
    Span,
    TextEdit,
)
from signals.policy.path import to_repo_relative
from signals.policy.severity import severity_for_ruff


# =============================================================================
# Unified Diff Parsing for ruff format --diff
# =============================================================================

# Regex patterns for unified diff parsing
_FILE_HEADER_PATTERN = re.compile(r"^--- (.+)$")
_FILE_HEADER_PLUS_PATTERN = re.compile(r"^\+\+\+ (.+)$")
_HUNK_HEADER_PATTERN = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)


@dataclass
class DiffHunk:
    """
    Represents a single hunk from a unified diff.

    A hunk describes a contiguous region of changes in a file,
    containing the original lines (removed) and new lines (added).
    """
    old_start: int      # Starting line in original file (1-based)
    old_count: int      # Number of lines in original section
    new_start: int      # Starting line in new file (1-based)
    new_count: int      # Number of lines in new section
    old_lines: list[str]  # Original content lines (without - prefix)
    new_lines: list[str]  # New content lines (without + prefix)


@dataclass
class FileDiff:
    """
    Represents all changes to a single file from a unified diff.

    Contains the file path and all hunks (change regions) for that file.
    """
    file_path: str
    hunks: list[DiffHunk]


def _parse_unified_diff(diff_text: str) -> list[FileDiff]:
    """
    Parse unified diff text into structured FileDiff objects.

    Handles standard unified diff format as produced by:
      - ruff format --diff
      - git diff
      - diff -u

    Args:
        diff_text: Raw unified diff text

    Returns:
        List of FileDiff objects, one per file changed
    """
    file_diffs: list[FileDiff] = []
    current_file: Optional[str] = None
    current_hunks: list[DiffHunk] = []
    current_hunk: Optional[DiffHunk] = None
    in_hunk = False

    lines = diff_text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check for file header (--- path)
        file_match = _FILE_HEADER_PATTERN.match(line)
        if file_match:
            # Save previous file if exists
            if current_file is not None and current_hunks:
                file_diffs.append(FileDiff(file_path=current_file, hunks=current_hunks))

            # Start new file - look for +++ line
            if i + 1 < len(lines):
                plus_match = _FILE_HEADER_PLUS_PATTERN.match(lines[i + 1])
                if plus_match:
                    # Extract file path, removing common prefixes like a/ b/
                    raw_path = plus_match.group(1)
                    # Remove common diff prefixes (a/, b/, etc.)
                    if raw_path.startswith("b/"):
                        raw_path = raw_path[2:]
                    elif raw_path.startswith("a/"):
                        raw_path = raw_path[2:]
                    current_file = raw_path
                    current_hunks = []
                    current_hunk = None
                    in_hunk = False
                    i += 2
                    continue

            i += 1
            continue

        # Check for hunk header (@@ -start,count +start,count @@)
        hunk_match = _HUNK_HEADER_PATTERN.match(line)
        if hunk_match and current_file is not None:
            # Save previous hunk
            if current_hunk is not None:
                current_hunks.append(current_hunk)

            old_start = int(hunk_match.group(1))
            old_count = int(hunk_match.group(2)) if hunk_match.group(2) else 1
            new_start = int(hunk_match.group(3))
            new_count = int(hunk_match.group(4)) if hunk_match.group(4) else 1

            current_hunk = DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                old_lines=[],
                new_lines=[],
            )
            in_hunk = True
            i += 1
            continue

        # Parse hunk content
        if in_hunk and current_hunk is not None:
            if line.startswith("-"):
                # Removed line (part of original)
                current_hunk.old_lines.append(line[1:])
            elif line.startswith("+"):
                # Added line (part of new)
                current_hunk.new_lines.append(line[1:])
            elif line.startswith(" "):
                # Context line (in both old and new)
                current_hunk.old_lines.append(line[1:])
                current_hunk.new_lines.append(line[1:])
            elif line.startswith("\\"):
                # "\ No newline at end of file" - skip
                pass
            else:
                # Unknown line format or end of hunk
                pass

        i += 1

    # Save final hunk and file
    if current_hunk is not None:
        current_hunks.append(current_hunk)
    if current_file is not None and current_hunks:
        file_diffs.append(FileDiff(file_path=current_file, hunks=current_hunks))

    return file_diffs


def _hunk_to_fix_signal(
    file_path: str,
    hunk: DiffHunk,
    *,
    repo_root: str | None = None,
) -> FixSignal:
    """
    Convert a single diff hunk into a FixSignal.

    The hunk's old content defines the span to replace,
    and the new content defines what to replace it with.

    Args:
        file_path: Path to the file being modified
        hunk: The diff hunk to convert
        repo_root: Optional repository root for path normalization

    Returns:
        FixSignal representing the formatting change
    """
    normalized_path = to_repo_relative(file_path, repo_root)

    # Span covers the original lines that will be replaced
    # End position is exclusive, so we add old_count to get the line after the last affected line
    span = Span(
        start=Position(row=hunk.old_start, column=1),
        end=Position(row=hunk.old_start + hunk.old_count, column=1),
    )

    # Build the replacement content from new lines
    new_content = "\n".join(hunk.new_lines)
    if hunk.new_lines:
        new_content += "\n"  # Preserve trailing newline

    # Create TextEdit for the fix
    edit = TextEdit(span=span, content=new_content)

    # Create the Fix object
    # Format changes are always safe and deterministic
    fix = Fix(
        applicability=FixApplicability.SAFE,
        message="Apply ruff format",
        edits=[edit],
    )

    # Count changes for message
    removed = len([l for l in hunk.old_lines if l not in hunk.new_lines])
    added = len([l for l in hunk.new_lines if l not in hunk.old_lines])

    return FixSignal(
        signal_type=SignalType.FORMAT,
        severity=Severity.LOW,  # Format issues are always low severity
        file_path=normalized_path,
        span=span,
        rule_code="FORMAT",
        message=f"Formatting changes: {removed} line(s) modified, {added} line(s) reformatted",
        docs_url="https://docs.astral.sh/ruff/formatter/",
        fix=fix,
    )


def parse_ruff_format_diff(
    diff_text: str,
    *,
    repo_root: str | None = None,
    group_by_file: bool = True,
) -> list[FixSignal]:
    """
    Parse ruff format --diff output into normalized FixSignal objects.

    Ruff format produces unified diff output showing what formatting changes
    would be applied. This parser converts that diff into FixSignal objects
    that can be processed by the standard signal pipeline.

    Format signals have special characteristics:
      - SignalType.FORMAT (lowest priority in pipeline)
      - Severity.LOW (cosmetic changes only)
      - FixApplicability.SAFE (format is idempotent and safe)
      - Deterministic edits (no LLM needed by default)

    Args:
        diff_text: Raw output from `ruff format --diff`
        repo_root: Optional repository root for path normalization
        group_by_file: If True, creates one signal per file (all hunks merged).
                       If False, creates one signal per hunk (more granular).

    Returns:
        List of FixSignal objects representing formatting changes.
        Returns empty list if no formatting changes are needed.

    Example:
        >>> with open("ruff-format-output.txt") as f:
        ...     diff = f.read()
        >>> signals = parse_ruff_format_diff(diff, repo_root="/path/to/repo")
        >>> for sig in signals:
        ...     print(f"{sig.file_path}: {sig.message}")
    """
    if not diff_text or not diff_text.strip():
        return []

    file_diffs = _parse_unified_diff(diff_text)

    if not file_diffs:
        return []

    signals: list[FixSignal] = []

    if group_by_file:
        # Create one signal per file with all hunks merged into one fix
        for file_diff in file_diffs:
            if not file_diff.hunks:
                continue

            normalized_path = to_repo_relative(file_diff.file_path, repo_root)

            # Merge all hunks into a single fix with multiple edits
            edits: list[TextEdit] = []
            total_changes = 0

            for hunk in file_diff.hunks:
                span = Span(
                    start=Position(row=hunk.old_start, column=1),
                    end=Position(row=hunk.old_start + hunk.old_count, column=1),
                )
                new_content = "\n".join(hunk.new_lines)
                if hunk.new_lines:
                    new_content += "\n"
                edits.append(TextEdit(span=span, content=new_content))
                total_changes += len(hunk.old_lines) + len(hunk.new_lines)

            # Use span of first hunk for the signal
            first_hunk = file_diff.hunks[0]
            last_hunk = file_diff.hunks[-1]
            signal_span = Span(
                start=Position(row=first_hunk.old_start, column=1),
                end=Position(row=last_hunk.old_start + last_hunk.old_count, column=1),
            )

            fix = Fix(
                applicability=FixApplicability.SAFE,
                message=f"Apply {len(file_diff.hunks)} formatting change(s)",
                edits=edits,
            )

            signals.append(FixSignal(
                signal_type=SignalType.FORMAT,
                severity=Severity.LOW,
                file_path=normalized_path,
                span=signal_span,
                rule_code="FORMAT",
                message=f"{len(file_diff.hunks)} formatting region(s) to update ({total_changes} lines affected)",
                docs_url="https://docs.astral.sh/ruff/formatter/",
                fix=fix,
            ))
    else:
        # Create one signal per hunk (more granular)
        for file_diff in file_diffs:
            for hunk in file_diff.hunks:
                signal = _hunk_to_fix_signal(
                    file_diff.file_path,
                    hunk,
                    repo_root=repo_root,
                )
                signals.append(signal)

    return signals


def _parse_position(obj: dict[str, Any]) -> Position:
    return Position(row=int(obj["row"]), column=int(obj["column"]))


def _parse_span(location: dict[str, Any], end_location: dict[str, Any]) -> Span:
    return Span(start=_parse_position(location), end=_parse_position(end_location))


def _parse_fix(fix_obj: dict[str, Any]) -> Fix:
    applicability_raw = (fix_obj.get("applicability") or "").lower()
    if applicability_raw == "safe":
        applicability = FixApplicability.SAFE
    elif applicability_raw == "unsafe":
        applicability = FixApplicability.UNSAFE
    else:
        applicability = FixApplicability.UNKNOWN

    edits: list[TextEdit] = []
    for e in fix_obj.get("edits", []):
        span = _parse_span(e["location"], e["end_location"])
        edits.append(TextEdit(span=span, content=str(e.get("content", ""))))

    return Fix(
        applicability=applicability,
        message=fix_obj.get("message"),
        edits=edits,
    )


def parse_ruff_lint_results(raw: str | Sequence[dict[str, Any]], *, repo_root: str | None = None,) -> list[FixSignal]:
    """
    Parse ruff-lint JSON (list of violation dicts) to normalized FixSignals.

    - Only implements Ruff for now.
    - Produces FixSignal.fix when Ruff provides deterministic edits.
    """
    violations: Iterable[dict[str, Any]]
    if isinstance(raw, str):
        violations = json.loads(raw)
    else:
        violations = raw

    signals: list[FixSignal] = []

    for v in violations:
        code = v.get("code")
        filename = v.get("filename")
        message = v.get("message", "")
        url = v.get("url")

        # Required fields sanity check (skip if malformed)
        if not code or not filename or "location" not in v or "end_location" not in v:
            # In production: log a warning with the record
            continue

        span = _parse_span(v["location"], v["end_location"])
        file_path = to_repo_relative(filename, repo_root)

        fix: Optional[Fix] = None
        if isinstance(v.get("fix"), dict):
            fix = _parse_fix(v["fix"])

        severity: Severity = severity_for_ruff(code)

        signals.append(
            FixSignal(
                signal_type=SignalType.LINT,
                severity=severity,
                file_path=file_path,
                span=span,
                rule_code=code,
                message=message,
                docs_url=url,
                fix=fix,
            )
        )

    return signals


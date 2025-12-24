# signals/parsers/ruff.py
from __future__ import annotations

import json
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


# -------------------------------------------------------------------------
# PSEUDOCODE PLACEHOLDERS
# -------------------------------------------------------------------------

# def parse_bandit_results(...):
#   """
#   PSEUDOCODE:
#     load JSON -> for each issue in data["results"]:
#       file/line/col + rule/test_id + issue_text + more_info + cwe
#       severity = severity_for_bandit(issue_severity, issue_confidence)
#       FixSignal.fix = None (almost always)
#   """
#   raise NotImplementedError

# def parse_mypy_results(...):
#   """
#   PSEUDOCODE:
#     mypy JSON can be newline-delimited objects or one JSON blob depending on flags.
#     for each error:
#       file/line/col + message + error_code
#       severity = severity_for_mypy(severity, error_code)
#       FixSignal.fix = None
#   """
#   raise NotImplementedError

# signals/parsers/__init__.py
"""
Signal parsers for various CI/CD tools.

Available parsers:
  - parse_ruff_lint_results: Parse ruff check --output-format=json
  - parse_ruff_format_diff: Parse ruff format --diff output
"""
from signals.parsers.ruff import (
    parse_ruff_lint_results,
    parse_ruff_format_diff,
    DiffHunk,
    FileDiff,
)

__all__ = [
    "parse_ruff_lint_results",
    "parse_ruff_format_diff",
    "DiffHunk",
    "FileDiff",
]

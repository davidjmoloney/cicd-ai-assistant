"""
Signal parsing and processing module.

This module handles the ingestion and structuring of CI/CD signals from various
tools like ruff, mypy, and bandit.
"""

from .models import (
    FixSignal,
    SignalType,
    Severity,
    Fix,
    FixApplicability,
    Position,
    Span,
    TextEdit,
)

__all__ = [
    "FixSignal",
    "SignalType",
    "Severity",
    "Fix",
    "FixApplicability",
    "Position",
    "Span",
    "TextEdit",
]

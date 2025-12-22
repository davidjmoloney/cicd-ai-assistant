"""
Signal parsing and processing module.

This module handles the ingestion and structuring of CI/CD signals from various
tools like ruff, mypy, and bandit.
"""

from .models import Signal, SignalGroup, SignalType, Severity

__all__ = ["Signal", "SignalGroup", "SignalType", "Severity"]

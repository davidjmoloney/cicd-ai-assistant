"""
Evaluation framework for quantitative analysis of the CICD AI Assistant.

This module provides tools to:
- Define and load test cases from frozen CICD artifacts
- Run the assistant against test cases
- Evaluate PR quality via GitHub Copilot reviews
- Run regression tests locally
- Collect metrics and generate reports
"""

from .test_case import TestCase, TestCaseLoader, TestCaseResult
from .harness import EvaluationHarness, EvaluationConfig
from .metrics import MetricsCollector, EvaluationMetrics
from .report import ReportGenerator

__all__ = [
    "TestCase",
    "TestCaseLoader",
    "TestCaseResult",
    "EvaluationHarness",
    "EvaluationConfig",
    "MetricsCollector",
    "EvaluationMetrics",
    "ReportGenerator",
]

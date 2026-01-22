"""
Metrics Collection and Calculation.

Tracks evaluation results and computes aggregate metrics.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .test_case import TestCaseResult, ReviewVerdict


@dataclass
class EvaluationMetrics:
    """
    Aggregate metrics from an evaluation run.

    Core metrics:
    - fix_success_rate: % of test cases that resulted in successful fixes
    - pr_creation_rate: % of test cases that created PRs
    - review_approval_rate: % of reviewed PRs that were approved
    - regression_pass_rate: % of test cases where regression tests passed

    Breakdown metrics:
    - by_tool: Counts per tool (ruff, mypy, bandit)
    - by_signal_type: Counts per signal type (lint, type_check, security)
    - by_error_code: Counts per specific error code
    """
    # Counts
    total_cases: int = 0
    successful_fixes: int = 0
    prs_created: int = 0
    reviews_completed: int = 0
    reviews_approved: int = 0
    regression_runs: int = 0
    regression_passed: int = 0

    # Rates (as percentages)
    fix_success_rate: float = 0.0
    pr_creation_rate: float = 0.0
    review_approval_rate: Optional[float] = None
    regression_pass_rate: Optional[float] = None

    # Confidence stats
    avg_confidence: float = 0.0
    min_confidence: float = 0.0
    max_confidence: float = 0.0

    # Timing stats
    avg_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0

    # Breakdowns
    by_tool: dict[str, int] = field(default_factory=dict)
    by_signal_type: dict[str, int] = field(default_factory=dict)
    by_error_code: dict[str, dict] = field(default_factory=dict)

    # Success rates by tool
    success_rate_by_tool: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "summary": {
                "total_cases": self.total_cases,
                "successful_fixes": self.successful_fixes,
                "prs_created": self.prs_created,
                "fix_success_rate": round(self.fix_success_rate, 2),
                "pr_creation_rate": round(self.pr_creation_rate, 2),
                "review_approval_rate": round(self.review_approval_rate, 2) if self.review_approval_rate else None,
                "regression_pass_rate": round(self.regression_pass_rate, 2) if self.regression_pass_rate else None,
            },
            "confidence": {
                "average": round(self.avg_confidence, 3),
                "min": round(self.min_confidence, 3),
                "max": round(self.max_confidence, 3),
            },
            "timing": {
                "average_seconds": round(self.avg_duration_seconds, 2),
                "total_seconds": round(self.total_duration_seconds, 2),
            },
            "by_tool": self.by_tool,
            "success_rate_by_tool": {k: round(v, 2) for k, v in self.success_rate_by_tool.items()},
            "by_signal_type": self.by_signal_type,
            "by_error_code": self.by_error_code,
        }


class MetricsCollector:
    """
    Collects test case results and computes metrics.

    Usage:
        collector = MetricsCollector()
        for result in results:
            collector.add_result(result)
        metrics = collector.compute_metrics()
    """

    def __init__(self) -> None:
        """Initialize the collector."""
        self.results: list[TestCaseResult] = []

    def add_result(self, result: TestCaseResult) -> None:
        """Add a test case result to the collection."""
        self.results.append(result)

    def clear(self) -> None:
        """Clear all collected results."""
        self.results = []

    def compute_metrics(self) -> EvaluationMetrics:
        """
        Compute aggregate metrics from collected results.

        Returns:
            EvaluationMetrics with all computed values
        """
        if not self.results:
            return EvaluationMetrics()

        metrics = EvaluationMetrics()
        metrics.total_cases = len(self.results)

        # Count basic stats
        prs_created = 0
        successful = 0
        reviews_completed = 0
        reviews_approved = 0
        regression_runs = 0
        regression_passed = 0

        confidences = []
        durations = []

        by_tool: dict[str, list[TestCaseResult]] = defaultdict(list)
        by_signal_type: dict[str, int] = defaultdict(int)
        by_error_code: dict[str, dict] = defaultdict(lambda: {"total": 0, "success": 0})

        for result in self.results:
            tc = result.test_case

            # Tool breakdown
            by_tool[tc.tool].append(result)

            # Signal type breakdown
            by_signal_type[tc.signal_type] += 1

            # Error code breakdown
            by_error_code[tc.error_code]["total"] += 1
            if result.is_successful:
                by_error_code[tc.error_code]["success"] += 1

            # PR creation
            if result.pr_created:
                prs_created += 1

            # Success
            if result.is_successful:
                successful += 1

            # Reviews
            if result.review_result:
                reviews_completed += 1
                if result.review_result.verdict == ReviewVerdict.APPROVED:
                    reviews_approved += 1

            # Regression tests
            if result.regression_result:
                regression_runs += 1
                if result.regression_result.failed == 0 and result.regression_result.errors == 0:
                    regression_passed += 1

            # Confidence
            if result.fix_confidence is not None:
                confidences.append(result.fix_confidence)

            # Duration
            if result.duration_seconds is not None:
                durations.append(result.duration_seconds)

        # Compute rates
        metrics.prs_created = prs_created
        metrics.successful_fixes = successful
        metrics.reviews_completed = reviews_completed
        metrics.reviews_approved = reviews_approved
        metrics.regression_runs = regression_runs
        metrics.regression_passed = regression_passed

        metrics.fix_success_rate = (successful / metrics.total_cases) * 100
        metrics.pr_creation_rate = (prs_created / metrics.total_cases) * 100

        if reviews_completed > 0:
            metrics.review_approval_rate = (reviews_approved / reviews_completed) * 100

        if regression_runs > 0:
            metrics.regression_pass_rate = (regression_passed / regression_runs) * 100

        # Confidence stats
        if confidences:
            metrics.avg_confidence = sum(confidences) / len(confidences)
            metrics.min_confidence = min(confidences)
            metrics.max_confidence = max(confidences)

        # Timing stats
        if durations:
            metrics.avg_duration_seconds = sum(durations) / len(durations)
            metrics.total_duration_seconds = sum(durations)

        # Breakdowns
        metrics.by_tool = {tool: len(results) for tool, results in by_tool.items()}
        metrics.by_signal_type = dict(by_signal_type)
        metrics.by_error_code = dict(by_error_code)

        # Success rate by tool
        for tool, tool_results in by_tool.items():
            tool_success = sum(1 for r in tool_results if r.is_successful)
            metrics.success_rate_by_tool[tool] = (tool_success / len(tool_results)) * 100 if tool_results else 0.0

        return metrics

    def get_failures(self) -> list[TestCaseResult]:
        """Get all failed test case results."""
        return [r for r in self.results if not r.is_successful]

    def get_successes(self) -> list[TestCaseResult]:
        """Get all successful test case results."""
        return [r for r in self.results if r.is_successful]

    def get_by_tool(self, tool: str) -> list[TestCaseResult]:
        """Get results for a specific tool."""
        return [r for r in self.results if r.test_case.tool == tool]

    def get_by_error_code(self, error_code: str) -> list[TestCaseResult]:
        """Get results for a specific error code."""
        return [r for r in self.results if r.test_case.error_code == error_code]


def compare_runs(run1_metrics: EvaluationMetrics, run2_metrics: EvaluationMetrics) -> dict:
    """
    Compare metrics between two evaluation runs.

    Useful for measuring improvement over time or comparing different configurations.

    Returns:
        Dictionary with delta values and percentage changes
    """
    def calc_delta(v1: float, v2: float) -> dict:
        delta = v2 - v1
        pct_change = ((v2 - v1) / v1 * 100) if v1 != 0 else 0
        return {"delta": delta, "percent_change": pct_change}

    return {
        "fix_success_rate": calc_delta(run1_metrics.fix_success_rate, run2_metrics.fix_success_rate),
        "pr_creation_rate": calc_delta(run1_metrics.pr_creation_rate, run2_metrics.pr_creation_rate),
        "avg_confidence": calc_delta(run1_metrics.avg_confidence, run2_metrics.avg_confidence),
        "review_approval_rate": calc_delta(
            run1_metrics.review_approval_rate or 0,
            run2_metrics.review_approval_rate or 0,
        ) if run1_metrics.review_approval_rate and run2_metrics.review_approval_rate else None,
        "regression_pass_rate": calc_delta(
            run1_metrics.regression_pass_rate or 0,
            run2_metrics.regression_pass_rate or 0,
        ) if run1_metrics.regression_pass_rate and run2_metrics.regression_pass_rate else None,
        "by_tool": {
            tool: calc_delta(
                run1_metrics.success_rate_by_tool.get(tool, 0),
                run2_metrics.success_rate_by_tool.get(tool, 0),
            )
            for tool in set(run1_metrics.by_tool.keys()) | set(run2_metrics.by_tool.keys())
        },
    }

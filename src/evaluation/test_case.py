"""
Test case model and loader for the evaluation framework.

Each test case represents a single CICD error to be evaluated.
Test cases are defined in YAML files and loaded with their associated artifacts.
"""

from __future__ import annotations

import json
import yaml
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class TestCaseStatus(str, Enum):
    """Status of a test case evaluation."""
    PENDING = "pending"
    RUNNING = "running"
    PR_CREATED = "pr_created"
    REVIEW_PENDING = "review_pending"
    REVIEW_COMPLETE = "review_complete"
    TESTS_RUNNING = "tests_running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ReviewVerdict(str, Enum):
    """Verdict from the code reviewer."""
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    COMMENTED = "commented"
    PENDING = "pending"
    ERROR = "error"


@dataclass
class TestCase:
    """
    A single test case representing one CICD error to evaluate.

    Attributes:
        id: Unique identifier for this test case
        tool: The CICD tool that produced this error (ruff, mypy, bandit)
        signal_type: Type of signal (lint, format, type_check, security)
        artifact_path: Path to the frozen artifact file
        error_code: Specific error code (e.g., "F401", "arg-type")
        file_path: Target file containing the error
        line_number: Line number of the error (if applicable)
        message: The error message
        description: Human-readable description of what this test validates
        expected_outcome: What we expect (fix, partial_fix, skip)
        tags: Optional tags for filtering/grouping
    """
    id: str
    tool: str
    signal_type: str
    artifact_path: str
    error_code: str
    file_path: str
    message: str
    description: str
    line_number: Optional[int] = None
    expected_outcome: str = "fix"
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate test case fields."""
        valid_tools = {"ruff", "mypy", "bandit", "ruff-format"}
        if self.tool not in valid_tools:
            raise ValueError(f"Invalid tool '{self.tool}'. Must be one of {valid_tools}")

        valid_signal_types = {"lint", "format", "type_check", "security"}
        if self.signal_type not in valid_signal_types:
            raise ValueError(f"Invalid signal_type '{self.signal_type}'")

        valid_outcomes = {"fix", "partial_fix", "skip", "fail"}
        if self.expected_outcome not in valid_outcomes:
            raise ValueError(f"Invalid expected_outcome '{self.expected_outcome}'")


@dataclass
class ReviewResult:
    """Result from a code review."""
    verdict: ReviewVerdict
    reviewer: str  # "copilot" or other reviewer identifier
    feedback: str
    quality_score: Optional[int] = None  # 1-5 scale if available
    review_url: Optional[str] = None
    reviewed_at: Optional[datetime] = None


@dataclass
class RegressionResult:
    """Result from running regression tests."""
    passed: int
    failed: int
    skipped: int
    errors: int
    total: int
    duration_seconds: float
    failure_details: list[dict] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate as a percentage."""
        if self.total == 0:
            return 0.0
        return (self.passed / self.total) * 100


@dataclass
class TestCaseResult:
    """
    Complete result of evaluating a single test case.

    Captures all stages: PR creation, review, and regression testing.
    """
    test_case: TestCase
    status: TestCaseStatus

    # PR creation results
    pr_created: bool = False
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    pr_branch: Optional[str] = None
    fix_confidence: Optional[float] = None

    # Review results
    review_result: Optional[ReviewResult] = None

    # Regression test results
    regression_result: Optional[RegressionResult] = None

    # Error tracking
    error_message: Optional[str] = None
    error_stage: Optional[str] = None

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate total duration if start and end times are set."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def is_successful(self) -> bool:
        """
        Determine if this test case was successful.

        Success criteria:
        - PR was created
        - Review was approved (or changes_requested is acceptable for partial_fix)
        - Regression tests passed (or maintained)
        """
        if not self.pr_created:
            return False

        if self.review_result:
            if self.review_result.verdict == ReviewVerdict.APPROVED:
                return True
            if (self.review_result.verdict == ReviewVerdict.CHANGES_REQUESTED
                and self.test_case.expected_outcome == "partial_fix"):
                return True

        return False

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "test_case_id": self.test_case.id,
            "tool": self.test_case.tool,
            "error_code": self.test_case.error_code,
            "file_path": self.test_case.file_path,
            "status": self.status.value,
            "pr_created": self.pr_created,
            "pr_url": self.pr_url,
            "pr_number": self.pr_number,
            "fix_confidence": self.fix_confidence,
            "review": {
                "verdict": self.review_result.verdict.value if self.review_result else None,
                "feedback": self.review_result.feedback if self.review_result else None,
                "quality_score": self.review_result.quality_score if self.review_result else None,
            } if self.review_result else None,
            "regression": {
                "passed": self.regression_result.passed,
                "failed": self.regression_result.failed,
                "total": self.regression_result.total,
                "pass_rate": self.regression_result.pass_rate,
            } if self.regression_result else None,
            "is_successful": self.is_successful,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class TestCaseLoader:
    """
    Loads test cases from YAML configuration files.

    Test cases can be defined in a single YAML file or across multiple files
    in a directory. Each test case references a frozen artifact file.
    """

    def __init__(self, base_path: Path):
        """
        Initialize the loader.

        Args:
            base_path: Base path for resolving relative artifact paths
        """
        self.base_path = Path(base_path)

    def load_from_file(self, config_path: Path) -> list[TestCase]:
        """
        Load test cases from a YAML configuration file.

        Args:
            config_path: Path to the YAML configuration file

        Returns:
            List of TestCase objects
        """
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        test_cases = []
        for case_data in config.get("test_cases", []):
            # Resolve artifact path relative to base_path
            artifact_path = case_data.get("artifact_path", "")
            if artifact_path and not Path(artifact_path).is_absolute():
                artifact_path = str(self.base_path / artifact_path)

            test_case = TestCase(
                id=case_data["id"],
                tool=case_data["tool"],
                signal_type=case_data["signal_type"],
                artifact_path=artifact_path,
                error_code=case_data["error_code"],
                file_path=case_data["file_path"],
                line_number=case_data.get("line_number"),
                message=case_data["message"],
                description=case_data.get("description", ""),
                expected_outcome=case_data.get("expected_outcome", "fix"),
                tags=case_data.get("tags", []),
            )
            test_cases.append(test_case)

        return test_cases

    def load_from_directory(self, dir_path: Path) -> list[TestCase]:
        """
        Load test cases from all YAML files in a directory.

        Args:
            dir_path: Path to directory containing YAML files

        Returns:
            List of TestCase objects from all files
        """
        test_cases = []
        yaml_files = list(Path(dir_path).glob("*.yaml")) + list(Path(dir_path).glob("*.yml"))

        for yaml_file in sorted(yaml_files):
            test_cases.extend(self.load_from_file(yaml_file))

        return test_cases

    def filter_by_tool(self, test_cases: list[TestCase], tool: str) -> list[TestCase]:
        """Filter test cases by tool."""
        return [tc for tc in test_cases if tc.tool == tool]

    def filter_by_tags(self, test_cases: list[TestCase], tags: list[str]) -> list[TestCase]:
        """Filter test cases that have any of the specified tags."""
        return [tc for tc in test_cases if any(tag in tc.tags for tag in tags)]

    def filter_by_signal_type(self, test_cases: list[TestCase], signal_type: str) -> list[TestCase]:
        """Filter test cases by signal type."""
        return [tc for tc in test_cases if tc.signal_type == signal_type]


def extract_test_cases_from_artifact(
    artifact_path: Path,
    tool: str,
    signal_type: str,
) -> list[TestCase]:
    """
    Auto-generate test cases from a CICD artifact file.

    This is useful for bootstrapping test cases from existing artifacts
    without manually writing YAML.

    Args:
        artifact_path: Path to the artifact file (JSON)
        tool: Tool that produced the artifact (ruff, mypy, bandit)
        signal_type: Type of signal (lint, type_check, security)

    Returns:
        List of auto-generated TestCase objects
    """
    with open(artifact_path, "r") as f:
        if tool == "mypy":
            # MyPy uses newline-delimited JSON
            lines = f.readlines()
            errors = [json.loads(line) for line in lines if line.strip()]
        else:
            errors = json.load(f)

    test_cases = []

    for i, error in enumerate(errors):
        if tool == "ruff":
            test_case = TestCase(
                id=f"{tool}-{error.get('code', 'unknown')}-{i+1}",
                tool=tool,
                signal_type=signal_type,
                artifact_path=str(artifact_path),
                error_code=error.get("code", "unknown"),
                file_path=error.get("filename", ""),
                line_number=error.get("location", {}).get("row"),
                message=error.get("message", ""),
                description=f"Auto-generated: {error.get('code')} in {error.get('filename')}",
            )
        elif tool == "mypy":
            test_case = TestCase(
                id=f"{tool}-{error.get('code', 'unknown')}-{i+1}",
                tool=tool,
                signal_type=signal_type,
                artifact_path=str(artifact_path),
                error_code=error.get("code", "unknown"),
                file_path=error.get("file", ""),
                line_number=error.get("line"),
                message=error.get("message", ""),
                description=f"Auto-generated: {error.get('code')} in {error.get('file')}",
            )
        elif tool == "bandit":
            test_case = TestCase(
                id=f"{tool}-{error.get('test_id', 'unknown')}-{i+1}",
                tool=tool,
                signal_type=signal_type,
                artifact_path=str(artifact_path),
                error_code=error.get("test_id", "unknown"),
                file_path=error.get("filename", ""),
                line_number=error.get("line_number"),
                message=error.get("issue_text", ""),
                description=f"Auto-generated: {error.get('test_id')} in {error.get('filename')}",
            )
        else:
            continue

        test_cases.append(test_case)

    return test_cases

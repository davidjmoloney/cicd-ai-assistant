"""
Evaluation Harness - Orchestrates the full evaluation loop.

Runs the CICD assistant against test cases and collects results.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# Optional dotenv support
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from .test_case import (
    TestCase,
    TestCaseLoader,
    TestCaseResult,
    TestCaseStatus,
    ReviewResult,
    RegressionResult,
)
from .reviewer import CopilotReviewer, ReviewerConfig
from .regression import RegressionRunner, RegressionConfig
from .metrics import MetricsCollector, EvaluationMetrics


@dataclass
class EvaluationConfig:
    """
    Configuration for the evaluation harness.

    Attributes:
        test_repo_owner: Owner of the forked test repository
        test_repo_name: Name of the forked test repository
        test_repo_branch: Base branch for PRs in test repo
        artifact_base_path: Base path for frozen artifacts
        test_case_path: Path to test case definitions
        results_output_path: Directory for evaluation results
        llm_provider: LLM provider for fix generation
        repo_root: Local path to test repo clone (for regression tests)
        skip_review: Skip the review step (for faster iteration)
        skip_regression: Skip regression tests
        max_concurrent: Max concurrent evaluations (not yet implemented)
        dry_run: If True, don't create actual PRs
    """
    test_repo_owner: str
    test_repo_name: str
    test_repo_branch: str = "main"
    artifact_base_path: str = "evaluation/artifacts"
    test_case_path: str = "evaluation/test_cases"
    results_output_path: str = "evaluation/results"
    llm_provider: str = "openai"
    repo_root: Optional[str] = None
    skip_review: bool = False
    skip_regression: bool = False
    max_concurrent: int = 1
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> "EvaluationConfig":
        """Create config from environment variables."""
        return cls(
            test_repo_owner=os.getenv("EVAL_REPO_OWNER", ""),
            test_repo_name=os.getenv("EVAL_REPO_NAME", ""),
            test_repo_branch=os.getenv("EVAL_REPO_BRANCH", "main"),
            artifact_base_path=os.getenv("EVAL_ARTIFACT_PATH", "evaluation/artifacts"),
            test_case_path=os.getenv("EVAL_TEST_CASE_PATH", "evaluation/test_cases"),
            results_output_path=os.getenv("EVAL_RESULTS_PATH", "evaluation/results"),
            llm_provider=os.getenv("LLM_PROVIDER", "openai"),
            repo_root=os.getenv("EVAL_REPO_ROOT"),
            skip_review=os.getenv("EVAL_SKIP_REVIEW", "false").lower() == "true",
            skip_regression=os.getenv("EVAL_SKIP_REGRESSION", "false").lower() == "true",
            dry_run=os.getenv("EVAL_DRY_RUN", "false").lower() == "true",
        )


@dataclass
class EvaluationRun:
    """
    Represents a complete evaluation run.

    Tracks all test case results and metadata about the run.
    """
    run_id: str
    config: EvaluationConfig
    started_at: datetime
    completed_at: Optional[datetime] = None
    results: list[TestCaseResult] = field(default_factory=list)
    metrics: Optional[EvaluationMetrics] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "run_id": self.run_id,
            "config": {
                "test_repo": f"{self.config.test_repo_owner}/{self.config.test_repo_name}",
                "test_repo_branch": self.config.test_repo_branch,
                "llm_provider": self.config.llm_provider,
                "skip_review": self.config.skip_review,
                "skip_regression": self.config.skip_regression,
                "dry_run": self.config.dry_run,
            },
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "num_test_cases": len(self.results),
            "results": [r.to_dict() for r in self.results],
            "metrics": self.metrics.to_dict() if self.metrics else None,
        }


class EvaluationHarness:
    """
    Orchestrates the full evaluation loop.

    For each test case:
    1. Parse the frozen artifact to extract the specific error
    2. Run the CICD assistant to generate a fix
    3. Create a PR to the test repository
    4. Request GitHub Copilot review
    5. Run regression tests
    6. Record results

    Usage:
        config = EvaluationConfig(
            test_repo_owner="my-org",
            test_repo_name="ardessa-repo-test",
        )
        harness = EvaluationHarness(config)
        run = harness.run_evaluation()
    """

    def __init__(self, config: EvaluationConfig) -> None:
        """Initialize the evaluation harness."""
        self.config = config
        self._validate_config()

        # Initialize components
        self.test_case_loader = TestCaseLoader(Path(config.artifact_base_path))
        self.metrics_collector = MetricsCollector()

        # Lazy init these
        self._reviewer: Optional[CopilotReviewer] = None
        self._regression_runner: Optional[RegressionRunner] = None

        # Progress callback
        self._progress_callback: Optional[Callable[[TestCaseResult], None]] = None

    def _validate_config(self) -> None:
        """Validate configuration."""
        if not self.config.test_repo_owner:
            raise ValueError("test_repo_owner is required")
        if not self.config.test_repo_name:
            raise ValueError("test_repo_name is required")

    @property
    def reviewer(self) -> CopilotReviewer:
        """Lazy init reviewer."""
        if self._reviewer is None:
            self._reviewer = CopilotReviewer(ReviewerConfig(
                repo_owner=self.config.test_repo_owner,
                repo_name=self.config.test_repo_name,
            ))
        return self._reviewer

    @property
    def regression_runner(self) -> RegressionRunner:
        """Lazy init regression runner."""
        if self._regression_runner is None:
            if not self.config.repo_root:
                raise ValueError("repo_root is required for regression tests")
            self._regression_runner = RegressionRunner(RegressionConfig(
                repo_path=self.config.repo_root,
            ))
        return self._regression_runner

    def set_progress_callback(self, callback: Callable[[TestCaseResult], None]) -> None:
        """Set a callback to be called after each test case completes."""
        self._progress_callback = callback

    def run_evaluation(
        self,
        test_cases: Optional[list[TestCase]] = None,
        filter_tool: Optional[str] = None,
        filter_tags: Optional[list[str]] = None,
    ) -> EvaluationRun:
        """
        Run the full evaluation.

        Args:
            test_cases: Explicit list of test cases (if None, loads from config path)
            filter_tool: Only run test cases for this tool
            filter_tags: Only run test cases with these tags

        Returns:
            EvaluationRun with all results and metrics
        """
        # Generate run ID
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Load test cases
        if test_cases is None:
            test_case_path = Path(self.config.test_case_path)
            if test_case_path.is_dir():
                test_cases = self.test_case_loader.load_from_directory(test_case_path)
            else:
                test_cases = self.test_case_loader.load_from_file(test_case_path)

        # Apply filters
        if filter_tool:
            test_cases = self.test_case_loader.filter_by_tool(test_cases, filter_tool)
        if filter_tags:
            test_cases = self.test_case_loader.filter_by_tags(test_cases, filter_tags)

        # Create run
        run = EvaluationRun(
            run_id=run_id,
            config=self.config,
            started_at=datetime.now(),
        )

        print(f"Starting evaluation run {run_id}")
        print(f"Test cases: {len(test_cases)}")
        print(f"Target repo: {self.config.test_repo_owner}/{self.config.test_repo_name}")
        print("-" * 60)

        # Run each test case
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n[{i}/{len(test_cases)}] Running: {test_case.id}")
            print(f"  Tool: {test_case.tool}, Error: {test_case.error_code}")

            result = self._run_single_test_case(test_case)
            run.results.append(result)
            self.metrics_collector.add_result(result)

            # Progress callback
            if self._progress_callback:
                self._progress_callback(result)

            # Print status
            status_icon = "✓" if result.is_successful else "✗"
            print(f"  {status_icon} Status: {result.status.value}")
            if result.pr_url:
                print(f"    PR: {result.pr_url}")
            if result.error_message:
                print(f"    Error: {result.error_message}")

        # Finalize run
        run.completed_at = datetime.now()
        run.metrics = self.metrics_collector.compute_metrics()

        # Save results
        self._save_results(run)

        # Print summary
        self._print_summary(run)

        return run

    def _run_single_test_case(self, test_case: TestCase) -> TestCaseResult:
        """
        Run a single test case through the full evaluation pipeline.

        Steps:
        1. Parse artifact and extract the specific signal
        2. Generate fix plan via orchestrator
        3. Create PR (unless dry run)
        4. Request review (unless skipped)
        5. Run regression tests (unless skipped)
        """
        result = TestCaseResult(
            test_case=test_case,
            status=TestCaseStatus.RUNNING,
            started_at=datetime.now(),
        )

        try:
            # Step 1: Parse artifact and create signal
            signal = self._extract_signal_from_artifact(test_case)
            if signal is None:
                result.status = TestCaseStatus.FAILED
                result.error_message = "Could not extract signal from artifact"
                result.error_stage = "parsing"
                result.completed_at = datetime.now()
                return result

            # Step 2: Generate fix plan
            fix_plan_result = self._generate_fix_plan(test_case, signal)
            if not fix_plan_result["success"]:
                result.status = TestCaseStatus.FAILED
                result.error_message = fix_plan_result.get("error", "Unknown error")
                result.error_stage = "fix_generation"
                result.completed_at = datetime.now()
                return result

            fix_plan = fix_plan_result["fix_plan"]
            result.fix_confidence = fix_plan.confidence

            # Step 3: Create PR
            if self.config.dry_run:
                result.status = TestCaseStatus.COMPLETED
                result.pr_created = False
                result.completed_at = datetime.now()
                return result

            pr_result = self._create_pr(fix_plan)
            if not pr_result["success"]:
                result.status = TestCaseStatus.FAILED
                result.error_message = pr_result.get("error", "Unknown error")
                result.error_stage = "pr_creation"
                result.completed_at = datetime.now()
                return result

            result.pr_created = True
            result.pr_url = pr_result["pr_url"]
            result.pr_number = pr_result["pr_number"]
            result.pr_branch = pr_result["branch_name"]
            result.status = TestCaseStatus.PR_CREATED

            # Step 4: Request review
            if not self.config.skip_review and result.pr_number:
                result.status = TestCaseStatus.REVIEW_PENDING
                review_result = self._request_review(result.pr_number)
                result.review_result = review_result
                result.status = TestCaseStatus.REVIEW_COMPLETE

            # Step 5: Run regression tests
            if not self.config.skip_regression and result.pr_branch:
                result.status = TestCaseStatus.TESTS_RUNNING
                regression_result = self._run_regression_tests(result.pr_branch)
                result.regression_result = regression_result

            result.status = TestCaseStatus.COMPLETED
            result.completed_at = datetime.now()
            return result

        except Exception as e:
            result.status = TestCaseStatus.FAILED
            result.error_message = str(e)
            result.error_stage = "unknown"
            result.completed_at = datetime.now()
            return result

    def _extract_signal_from_artifact(self, test_case: TestCase):
        """
        Extract the specific signal from the artifact file.

        Returns the FixSignal matching the test case, or None if not found.
        """
        from signals.parsers.ruff import parse_ruff_lint_results
        from signals.parsers.mypy import parse_mypy_results

        artifact_path = Path(test_case.artifact_path)
        if not artifact_path.exists():
            return None

        try:
            with open(artifact_path, "r") as f:
                content = f.read()

            # Parse based on tool
            if test_case.tool == "ruff":
                signals = parse_ruff_lint_results(content)
            elif test_case.tool == "mypy":
                signals = parse_mypy_results(content)
            else:
                # TODO: Add bandit parser
                return None

            # Find the matching signal
            for signal in signals:
                if (signal.file_path == test_case.file_path and
                    signal.rule_code == test_case.error_code):
                    # If line number is specified, match that too
                    if test_case.line_number:
                        if signal.span and signal.span.start.row == test_case.line_number:
                            return signal
                    else:
                        return signal

            # If no exact match, return first matching error code
            for signal in signals:
                if signal.rule_code == test_case.error_code:
                    return signal

            return None

        except Exception:
            return None

    def _generate_fix_plan(self, test_case: TestCase, signal) -> dict:
        """
        Generate a fix plan for the signal.

        Uses the existing orchestrator components.
        """
        from orchestrator.prioritizer import SignalGroup
        from orchestrator.fix_planner import FixPlanner
        from signals.models import SignalType

        try:
            # Create a signal group with just this signal
            signal_type_map = {
                "lint": SignalType.LINT,
                "format": SignalType.FORMAT,
                "type_check": SignalType.TYPE_CHECK,
                "security": SignalType.SECURITY,
            }
            signal_type = signal_type_map.get(test_case.signal_type, SignalType.LINT)

            group = SignalGroup(
                tool_id=test_case.tool,
                signal_type=signal_type,
                signals=[signal],
            )

            # Generate fix plan
            planner = FixPlanner(
                llm_provider=self.config.llm_provider,
                repo_root=self.config.repo_root,
            )
            result = planner.create_fix_plan(group)

            if result.success:
                return {
                    "success": True,
                    "fix_plan": result.fix_plan,
                    "used_llm": result.used_llm,
                }
            else:
                return {
                    "success": False,
                    "error": result.error,
                }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

    def _create_pr(self, fix_plan) -> dict:
        """
        Create a PR from the fix plan.

        Temporarily overrides target repo settings to use the test repo.
        """
        import os
        from github.pr_generator import PRGenerator

        # Save original settings
        original_owner = os.environ.get("TARGET_REPO_OWNER")
        original_name = os.environ.get("TARGET_REPO_NAME")
        original_branch = os.environ.get("TARGET_REPO_DEFAULT_BRANCH")

        try:
            # Override to use test repo
            os.environ["TARGET_REPO_OWNER"] = self.config.test_repo_owner
            os.environ["TARGET_REPO_NAME"] = self.config.test_repo_name
            os.environ["TARGET_REPO_DEFAULT_BRANCH"] = self.config.test_repo_branch

            # Need to reimport to pick up new env vars
            # This is a workaround for the module-level config pattern
            import importlib
            import github.pr_generator as pr_module
            importlib.reload(pr_module)

            generator = pr_module.PRGenerator()
            result = generator.create_pr(fix_plan, self.config.test_repo_branch)

            return {
                "success": result.success,
                "pr_url": result.pr_url,
                "pr_number": result.pr_number,
                "branch_name": result.branch_name,
                "error": result.error,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

        finally:
            # Restore original settings
            if original_owner:
                os.environ["TARGET_REPO_OWNER"] = original_owner
            if original_name:
                os.environ["TARGET_REPO_NAME"] = original_name
            if original_branch:
                os.environ["TARGET_REPO_DEFAULT_BRANCH"] = original_branch

    def _request_review(self, pr_number: int) -> ReviewResult:
        """Request a GitHub Copilot review on the PR."""
        return self.reviewer.request_review(pr_number)

    def _run_regression_tests(self, branch: str) -> RegressionResult:
        """Run regression tests on the PR branch."""
        return self.regression_runner.run_tests(branch)

    def _save_results(self, run: EvaluationRun) -> None:
        """Save evaluation results to disk."""
        output_dir = Path(self.config.results_output_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save JSON results
        json_path = output_dir / f"run_{run.run_id}.json"
        with open(json_path, "w") as f:
            json.dump(run.to_dict(), f, indent=2)

        print(f"\nResults saved to: {json_path}")

    def _print_summary(self, run: EvaluationRun) -> None:
        """Print evaluation summary."""
        print("\n" + "=" * 60)
        print("EVALUATION SUMMARY")
        print("=" * 60)

        if run.metrics:
            m = run.metrics
            print(f"Total test cases: {m.total_cases}")
            print(f"PRs created: {m.prs_created} ({m.pr_creation_rate:.1f}%)")
            print(f"Successful fixes: {m.successful_fixes} ({m.fix_success_rate:.1f}%)")

            if m.review_approval_rate is not None:
                print(f"Review approval rate: {m.review_approval_rate:.1f}%")
            if m.regression_pass_rate is not None:
                print(f"Regression pass rate: {m.regression_pass_rate:.1f}%")

            print(f"\nBy tool:")
            for tool, count in m.by_tool.items():
                success = sum(1 for r in run.results
                              if r.test_case.tool == tool and r.is_successful)
                print(f"  {tool}: {success}/{count}")

        print("=" * 60)


def run_evaluation_from_config() -> EvaluationRun:
    """
    Convenience function to run evaluation from environment config.

    Usage:
        from evaluation.harness import run_evaluation_from_config
        run = run_evaluation_from_config()
    """
    config = EvaluationConfig.from_env()
    harness = EvaluationHarness(config)
    return harness.run_evaluation()

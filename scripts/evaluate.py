#!/usr/bin/env python3
"""
Main Evaluation Script for CICD AI Assistant.

This script runs the evaluation framework to measure the performance
of the AI assistant in fixing CICD errors.

Usage:
    # Run with environment configuration
    python scripts/evaluate.py

    # Run with command-line options
    python scripts/evaluate.py --repo-owner my-org --repo-name ardessa-test

    # Run specific tools only
    python scripts/evaluate.py --tool ruff

    # Dry run (don't create actual PRs)
    python scripts/evaluate.py --dry-run

    # Skip reviews for faster iteration
    python scripts/evaluate.py --skip-review

Environment Variables:
    EVAL_REPO_OWNER         - Owner of the test repository
    EVAL_REPO_NAME          - Name of the test repository
    EVAL_REPO_BRANCH        - Base branch for PRs (default: main)
    EVAL_ARTIFACT_PATH      - Path to frozen artifacts (default: evaluation/artifacts)
    EVAL_TEST_CASE_PATH     - Path to test case definitions (default: evaluation/test_cases)
    EVAL_RESULTS_PATH       - Path for results output (default: evaluation/results)
    EVAL_REPO_ROOT          - Local path to test repo clone (for regression tests)
    EVAL_SKIP_REVIEW        - Skip Copilot reviews (default: false)
    EVAL_SKIP_REGRESSION    - Skip regression tests (default: false)
    EVAL_DRY_RUN            - Don't create PRs (default: false)
    LLM_PROVIDER            - LLM provider (default: openai)
    GITHUB_TOKEN            - GitHub PAT with repo access
"""

import argparse
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from evaluation.harness import EvaluationHarness, EvaluationConfig
from evaluation.test_case import TestCaseLoader, extract_test_cases_from_artifact
from evaluation.report import ReportGenerator


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Run CICD AI Assistant evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Repository configuration
    parser.add_argument(
        "--repo-owner",
        help="Owner of the test repository (overrides EVAL_REPO_OWNER)",
    )
    parser.add_argument(
        "--repo-name",
        help="Name of the test repository (overrides EVAL_REPO_NAME)",
    )
    parser.add_argument(
        "--repo-branch",
        default="main",
        help="Base branch for PRs (default: main)",
    )
    parser.add_argument(
        "--repo-root",
        help="Local path to test repo clone for regression tests",
    )

    # Test case configuration
    parser.add_argument(
        "--test-cases",
        help="Path to test case YAML file or directory",
    )
    parser.add_argument(
        "--artifacts",
        help="Path to frozen artifacts directory",
    )

    # Filters
    parser.add_argument(
        "--tool",
        choices=["ruff", "mypy", "bandit", "ruff-format"],
        help="Only run test cases for this tool",
    )
    parser.add_argument(
        "--tags",
        nargs="+",
        help="Only run test cases with these tags",
    )

    # Execution options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't create actual PRs (simulation mode)",
    )
    parser.add_argument(
        "--skip-review",
        action="store_true",
        help="Skip GitHub Copilot code review",
    )
    parser.add_argument(
        "--skip-regression",
        action="store_true",
        help="Skip regression test execution",
    )
    parser.add_argument(
        "--llm-provider",
        choices=["openai", "anthropic"],
        default="openai",
        help="LLM provider for fix generation (default: openai)",
    )

    # Output options
    parser.add_argument(
        "--output",
        help="Output directory for results (default: evaluation/results)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )

    # Special modes
    parser.add_argument(
        "--generate-cases",
        metavar="ARTIFACT_PATH",
        help="Generate test cases from an artifact file instead of running evaluation",
    )
    parser.add_argument(
        "--generate-tool",
        choices=["ruff", "mypy", "bandit"],
        help="Tool type for --generate-cases",
    )

    return parser.parse_args()


def generate_test_cases(artifact_path: str, tool: str) -> None:
    """Generate test cases from an artifact file."""
    import yaml

    path = Path(artifact_path)
    if not path.exists():
        print(f"Error: Artifact file not found: {artifact_path}")
        sys.exit(1)

    signal_type_map = {
        "ruff": "lint",
        "mypy": "type_check",
        "bandit": "security",
    }
    signal_type = signal_type_map.get(tool, "lint")

    print(f"Extracting test cases from: {artifact_path}")
    print(f"Tool: {tool}, Signal Type: {signal_type}")

    test_cases = extract_test_cases_from_artifact(path, tool, signal_type)

    print(f"Found {len(test_cases)} potential test cases")

    # Convert to YAML format
    yaml_data = {
        "test_cases": [
            {
                "id": tc.id,
                "tool": tc.tool,
                "signal_type": tc.signal_type,
                "artifact_path": tc.artifact_path,
                "error_code": tc.error_code,
                "file_path": tc.file_path,
                "line_number": tc.line_number,
                "message": tc.message,
                "description": tc.description,
                "expected_outcome": tc.expected_outcome,
                "tags": tc.tags,
            }
            for tc in test_cases
        ]
    }

    # Output YAML
    output_path = Path(f"evaluation/test_cases/{tool}_cases.yaml")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        yaml.dump(yaml_data, f, default_flow_style=False, sort_keys=False)

    print(f"Test cases written to: {output_path}")


def run_evaluation(args: argparse.Namespace) -> int:
    """Run the evaluation."""
    import os

    # Build configuration from args and environment
    config = EvaluationConfig(
        test_repo_owner=args.repo_owner or os.getenv("EVAL_REPO_OWNER", ""),
        test_repo_name=args.repo_name or os.getenv("EVAL_REPO_NAME", ""),
        test_repo_branch=args.repo_branch,
        artifact_base_path=args.artifacts or os.getenv("EVAL_ARTIFACT_PATH", "evaluation/artifacts"),
        test_case_path=args.test_cases or os.getenv("EVAL_TEST_CASE_PATH", "evaluation/test_cases"),
        results_output_path=args.output or os.getenv("EVAL_RESULTS_PATH", "evaluation/results"),
        llm_provider=args.llm_provider,
        repo_root=args.repo_root or os.getenv("EVAL_REPO_ROOT"),
        skip_review=args.skip_review or os.getenv("EVAL_SKIP_REVIEW", "false").lower() == "true",
        skip_regression=args.skip_regression or os.getenv("EVAL_SKIP_REGRESSION", "false").lower() == "true",
        dry_run=args.dry_run or os.getenv("EVAL_DRY_RUN", "false").lower() == "true",
    )

    # Validate required configuration
    if not config.test_repo_owner or not config.test_repo_name:
        print("Error: Repository owner and name are required.")
        print("Set via --repo-owner/--repo-name or EVAL_REPO_OWNER/EVAL_REPO_NAME environment variables.")
        return 1

    if not os.getenv("GITHUB_TOKEN"):
        print("Error: GITHUB_TOKEN environment variable is required.")
        return 1

    # Print configuration
    print("=" * 60)
    print("CICD AI Assistant Evaluation")
    print("=" * 60)
    print(f"Target: {config.test_repo_owner}/{config.test_repo_name}")
    print(f"Branch: {config.test_repo_branch}")
    print(f"LLM Provider: {config.llm_provider}")
    print(f"Dry Run: {config.dry_run}")
    print(f"Skip Review: {config.skip_review}")
    print(f"Skip Regression: {config.skip_regression}")
    print("=" * 60)

    try:
        # Create harness and run evaluation
        harness = EvaluationHarness(config)

        # Optional progress callback for verbose mode
        if args.verbose:
            def progress_callback(result):
                print(f"  Completed: {result.test_case.id} - {result.status.value}")
            harness.set_progress_callback(progress_callback)

        # Run evaluation
        run = harness.run_evaluation(
            filter_tool=args.tool,
            filter_tags=args.tags,
        )

        # Generate additional reports
        if run.results:
            report_gen = ReportGenerator(config.results_output_path)
            reports = report_gen.generate_all(run)

            print("\nReports generated:")
            for fmt, path in reports.items():
                print(f"  {fmt}: {path}")

        # Return exit code based on success rate
        if run.metrics:
            if run.metrics.fix_success_rate >= 80:
                return 0  # Success
            elif run.metrics.fix_success_rate >= 50:
                return 1  # Partial success
            else:
                return 2  # Failure
        return 0

    except Exception as e:
        print(f"\nError: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Special mode: generate test cases from artifact
    if args.generate_cases:
        if not args.generate_tool:
            print("Error: --generate-tool is required with --generate-cases")
            return 1
        generate_test_cases(args.generate_cases, args.generate_tool)
        return 0

    # Normal mode: run evaluation
    return run_evaluation(args)


if __name__ == "__main__":
    sys.exit(main())

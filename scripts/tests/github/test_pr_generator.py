#!/usr/bin/env python3
"""
Test script for PRGenerator.

Usage:
    # Fixture mode (no GitHub API calls)
    MAKE_LLM_CALL=false PYTHONPATH=src python scripts/tests/github/test_pr_generator.py

    # Live mode (requires GitHub token)
    MAKE_LLM_CALL=true PYTHONPATH=src python scripts/tests/github/test_pr_generator.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.test_base import BaseTest, TestResult
from agents.agent_handler import FixPlan
from github.pr_generator import PRGenerator, PRResult


class PRGeneratorTest(BaseTest[FixPlan, PRResult]):
    """Test PR generator."""

    def load_input(self) -> FixPlan:
        """Load fix plan input."""
        fix_plan_data = self.load_fixture("fixplan_input.json")
        return FixPlan.from_dict(fix_plan_data)

    def run_component(self, input_data: FixPlan) -> PRResult:
        """Run PR generator."""
        if self.use_live_mode:
            # Make live GitHub API call
            pr_gen = PRGenerator()
            return pr_gen.create_pr(fix_plan=input_data, base_branch="main")
        else:
            # Return mock result
            return PRResult(
                success=True,
                pr_url="https://github.com/test/repo/pull/123",
                pr_number=123,
                branch_name="cicd-agent-fix/test",
                files_changed=["file1.py", "file2.py"]
            )

    def validate_output(self, output: PRResult) -> TestResult[PRResult]:
        """Validate PR result."""
        result = TestResult(success=True, output=output)

        # Check success
        if self.assert_equals(output.success, True, "PR creation succeeded"):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        # Summary
        if output.success:
            print(f"\n  PR URL: {output.pr_url}")
            print(f"  Branch: {output.branch_name}")
            print(f"  Files changed: {len(output.files_changed)}")

        return result


def main():
    """Run the test."""
    from common.test_config import TestConfig
    config = TestConfig()

    test = PRGeneratorTest(
        fixture_dir=Path(__file__).parent / "fixtures",
        output_dir=Path(__file__).parent.parent.parent.parent / "scripts" / "debug" / "outputs",
        use_live_mode=config.make_llm_call,
    )

    result = test.run()
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()

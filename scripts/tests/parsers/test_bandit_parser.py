#!/usr/bin/env python3
"""
Test script for Bandit parser (STUB - Parser not yet implemented).

This is a stub test that demonstrates the pattern for adding new parser tests.
The Bandit parser (signals/parsers/bandit.py) is not yet implemented.

Inputs: scripts/tests/parsers/fixtures/bandit_input.json
Outputs: scripts/debug/outputs/output.json

Usage:
    PYTHONPATH=src python scripts/tests/parsers/test_bandit_parser.py

Expected result: Will print a warning that the parser is not implemented yet.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add common directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.test_base import BaseTest, TestResult
from signals.models import FixSignal


class BanditParserTest(BaseTest[dict, list[FixSignal]]):
    """Test Bandit parser (STUB)."""

    def load_input(self) -> dict:
        """Load Bandit JSON input fixture."""
        return self.load_fixture("bandit_input.json")

    def run_component(self, input_data: dict) -> list[FixSignal]:
        """
        Parse Bandit JSON to FixSignals.

        Args:
            input_data: Raw Bandit JSON

        Returns:
            List of normalized FixSignal objects

        Raises:
            NotImplementedError: Bandit parser not yet implemented
        """
        # TODO: Implement when signals/parsers/bandit.py is created
        # from signals.parsers.bandit import parse_bandit_results
        # return parse_bandit_results(input_data, repo_root=self.config.target_repo_root)

        raise NotImplementedError(
            "Bandit parser not yet implemented. "
            "Create signals/parsers/bandit.py with parse_bandit_results() function."
        )

    def validate_output(self, output: list[FixSignal]) -> TestResult[list[FixSignal]]:
        """
        Validate parsed signals against expected output.

        Args:
            output: List of FixSignal objects from parser

        Returns:
            TestResult with validation status
        """
        result = TestResult(success=True, output=output)

        # Load expected output
        expected = self.load_fixture("bandit_expected_signals.json")

        # Check signal count
        if self.assert_equals(
            len(output),
            len(expected),
            f"Signal count matches ({len(expected)} signals)"
        ):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        if not output or not expected:
            return result

        # Check first signal properties
        first_signal = output[0]
        first_expected = expected[0]

        if self.assert_equals(
            first_signal.rule_code,
            first_expected.get("rule_code"),
            f"First signal rule_code: {first_signal.rule_code}"
        ):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        if self.assert_equals(
            first_signal.signal_type.value,
            "security",
            "First signal type is 'security'"
        ):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        # Check severity mapping
        if self.assert_equals(
            first_signal.severity.value,
            first_expected.get("severity"),
            f"First signal severity: {first_signal.severity.value}"
        ):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        return result


def main():
    """Run the test."""
    print("=" * 80)
    print("Bandit Parser Test (STUB)")
    print("=" * 80)
    print("\n⚠ WARNING: Bandit parser is not yet implemented.")
    print("This is a stub test demonstrating the pattern for adding new parsers.")
    print("\nTo implement:")
    print("1. Create src/signals/parsers/bandit.py")
    print("2. Implement parse_bandit_results() function")
    print("3. Update this test to import and use the parser")
    print("4. Run: PYTHONPATH=src python scripts/tests/parsers/test_bandit_parser.py")
    print("=" * 80)

    # Uncomment when parser is implemented:
    # test = BanditParserTest(
    #     fixture_dir=Path(__file__).parent / "fixtures",
    #     output_dir=Path(__file__).parent.parent.parent.parent / "scripts" / "debug" / "outputs",
    #     use_live_mode=False,
    # )
    # result = test.run()
    # sys.exit(0 if result.success else 1)

    sys.exit(0)


if __name__ == "__main__":
    main()

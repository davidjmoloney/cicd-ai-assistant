#!/usr/bin/env python3
"""
Test script for Ruff parser.

Tests the Ruff JSON parser (signals/parsers/ruff.py) which converts Ruff lint
results into normalized FixSignal objects.

Inputs: scripts/tests/parsers/fixtures/ruff_input.json
Outputs: scripts/debug/outputs/output.json

Usage:
    PYTHONPATH=src python scripts/tests/parsers/test_ruff_parser.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add common directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.test_base import BaseTest, TestResult
from signals.parsers.ruff import parse_ruff_lint_results
from signals.models import FixSignal


class RuffParserTest(BaseTest[dict, list[FixSignal]]):
    """Test Ruff JSON parser."""

    def load_input(self) -> dict:
        """Load Ruff JSON input fixture."""
        return self.load_fixture("ruff_input.json")

    def run_component(self, input_data: dict) -> list[FixSignal]:
        """
        Parse Ruff JSON to FixSignals.

        Args:
            input_data: Raw Ruff JSON (list of violations)

        Returns:
            List of normalized FixSignal objects
        """
        return parse_ruff_lint_results(
            input_data,
            repo_root=self.config.target_repo_root,
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
        expected = self.load_fixture("ruff_expected_signals.json")

        # Assertion 1: Check signal count
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
            result.error = "No signals to validate"
            result.success = False
            return result

        # Assertion 2: Check first signal properties
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
            first_signal.severity.value,
            first_expected.get("severity"),
            f"First signal severity: {first_signal.severity.value}"
        ):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        if self.assert_equals(
            first_signal.message,
            first_expected.get("message"),
            "First signal message matches"
        ):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        # Assertion 3: Check that all signals have required fields
        missing_fields_count = 0
        for i, signal in enumerate(output):
            if not signal.file_path:
                print(f"  ✗ Signal {i}: Missing file_path")
                missing_fields_count += 1
            elif not signal.message:
                print(f"  ✗ Signal {i}: Missing message")
                missing_fields_count += 1

        if missing_fields_count == 0:
            print(f"  ✓ All {len(output)} signals have required fields")
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        # Assertion 4: Check signal types
        if all(signal.signal_type.value == "lint" for signal in output):
            print(f"  ✓ All signals have signal_type='lint'")
            result.assertions_passed += 1
        else:
            print(f"  ✗ Not all signals have signal_type='lint'")
            result.assertions_failed += 1
            result.success = False

        # Assertion 5: Check that signals with fixes have valid fix structures
        signals_with_fixes = [s for s in output if s.fix]
        if signals_with_fixes:
            all_fixes_valid = all(
                s.fix.edits and len(s.fix.edits) > 0
                for s in signals_with_fixes
            )
            if all_fixes_valid:
                print(f"  ✓ All {len(signals_with_fixes)} signals with fixes have valid edit structures")
                result.assertions_passed += 1
            else:
                print(f"  ✗ Some signals have invalid fix structures")
                result.assertions_failed += 1
                result.success = False

        # Summary information
        signals_with_safe_fixes = sum(
            1 for s in output if s.fix and s.fix.applicability.value == "safe"
        )
        print(f"\n  Summary:")
        print(f"    Total signals: {len(output)}")
        print(f"    Signals with fixes: {len(signals_with_fixes)}")
        print(f"    Signals with safe fixes: {signals_with_safe_fixes}")

        return result


def main():
    """Run the test."""
    test = RuffParserTest(
        fixture_dir=Path(__file__).parent / "fixtures",
        output_dir=Path(__file__).parent.parent.parent.parent / "scripts" / "debug" / "outputs",
        use_live_mode=False,
    )

    result = test.run()

    # Exit with appropriate code
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()

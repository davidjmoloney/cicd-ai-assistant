#!/usr/bin/env python3
"""
Test script for Prioritizer.

Tests the signal prioritization logic (orchestrator/prioritizer.py) which
groups FixSignals by tool and creates batches for agent processing.

Inputs: scripts/tests/orchestrator/fixtures/signals_input.json
Outputs: scripts/debug/outputs/output.json

Usage:
    PYTHONPATH=src python scripts/tests/orchestrator/test_prioritizer.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add common directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.test_base import BaseTest, TestResult
from signals.models import (
    FixSignal, SignalType, Severity, Span, Position,
    Fix, FixApplicability, TextEdit
)
from orchestrator.prioritizer import Prioritizer, SignalGroup


class PrioritizerTest(BaseTest[list[dict], list[SignalGroup]]):
    """Test signal prioritization."""

    def load_input(self) -> list[dict]:
        """Load FixSignal list from fixture."""
        return self.load_fixture("signals_input.json")

    def run_component(self, input_data: list[dict]) -> list[SignalGroup]:
        """
        Run the prioritizer.

        Args:
            input_data: List of FixSignal dicts

        Returns:
            List of SignalGroup objects
        """
        # Convert dicts back to FixSignal objects
        signals = []
        for sig_data in input_data:
            span = None
            if sig_data.get("span"):
                span = Span(
                    start=Position(**sig_data["span"]["start"]),
                    end=Position(**sig_data["span"]["end"])
                )

            fix = None
            if sig_data.get("fix"):
                fix_data = sig_data["fix"]
                edits = [
                    TextEdit(
                        span=Span(
                            start=Position(**e["span"]["start"]),
                            end=Position(**e["span"]["end"])
                        ),
                        content=e["content"]
                    )
                    for e in fix_data["edits"]
                ]
                fix = Fix(
                    applicability=FixApplicability(fix_data["applicability"]),
                    message=fix_data.get("message"),
                    edits=edits
                )

            signal = FixSignal(
                signal_type=SignalType(sig_data["signal_type"]),
                severity=Severity(sig_data["severity"]),
                file_path=sig_data["file_path"],
                span=span,
                rule_code=sig_data.get("rule_code"),
                message=sig_data["message"],
                docs_url=sig_data.get("docs_url"),
                fix=fix
            )
            signals.append(signal)

        # Run prioritizer
        prioritizer = Prioritizer()
        return prioritizer.prioritize(signals)

    def validate_output(self, output: list[SignalGroup]) -> TestResult[list[SignalGroup]]:
        """
        Validate prioritization output.

        Args:
            output: List of SignalGroup objects

        Returns:
            TestResult with validation status
        """
        result = TestResult(success=True, output=output)

        # Load expected
        expected = self.load_fixture("groups_expected.json")

        # Check group count
        if self.assert_equals(
            len(output),
            len(expected),
            f"Group count matches ({len(expected)} groups)"
        ):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        if not output:
            return result

        # Check first group
        first_group = output[0]
        first_expected = expected[0]

        if self.assert_equals(
            first_group.tool_id,
            first_expected["tool_id"],
            f"First group tool_id: {first_group.tool_id}"
        ):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        if self.assert_equals(
            len(first_group.signals),
            first_expected["signals_count"],
            f"First group signal count: {len(first_group.signals)}"
        ):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        # Summary
        print(f"\n  Summary:")
        print(f"    Total groups: {len(output)}")
        print(f"    Total signals across groups: {sum(len(g.signals) for g in output)}")

        return result


def main():
    """Run the test."""
    test = PrioritizerTest(
        fixture_dir=Path(__file__).parent / "fixtures",
        output_dir=Path(__file__).parent.parent.parent.parent / "scripts" / "debug" / "outputs",
        use_live_mode=False,
    )

    result = test.run()
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()

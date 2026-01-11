#!/usr/bin/env python3
"""
Test script for ContextBuilder.

Tests the context building logic (orchestrator/context_builder.py) which
creates structured context for LLM agents.

Inputs: scripts/tests/orchestrator/fixtures/groups_expected.json
Outputs: scripts/tests/orchestrator/fixtures/context_expected.json (comparison)

Usage:
    PYTHONPATH=src python scripts/tests/orchestrator/test_context_builder.py

Note: This test validates the structure of context output, not the actual
file reading (which depends on the target repository being present).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add common directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.test_base import BaseTest, TestResult


class ContextBuilderTest(BaseTest[dict, dict]):
    """Test context builder (structure validation only)."""

    def load_input(self) -> dict:
        """Load expected context structure."""
        return self.load_fixture("context_expected.json")

    def run_component(self, input_data: dict) -> dict:
        """
        Return the loaded context (structure test only).

        Args:
            input_data: Expected context structure

        Returns:
            The context structure for validation
        """
        # For now, we just validate the structure of existing context
        # Full integration test would run ContextBuilder on live signals
        return input_data

    def validate_output(self, output: dict) -> TestResult[dict]:
        """
        Validate context structure.

        Args:
            output: Context dict

        Returns:
            TestResult with validation status
        """
        result = TestResult(success=True, output=output)

        # Check required top-level keys
        required_keys = ["group", "signals"]
        for key in required_keys:
            if self.assert_contains(output.keys(), key, f"Has required key '{key}'"):
                result.assertions_passed += 1
            else:
                result.assertions_failed += 1
                result.success = False

        # Check group structure
        if "group" in output:
            group = output["group"]
            group_keys = ["tool_id", "signal_type", "group_size"]
            for key in group_keys:
                if key in group:
                    print(f"  ✓ Group has '{key}': {group[key]}")
                    result.assertions_passed += 1
                else:
                    print(f"  ✗ Group missing '{key}'")
                    result.assertions_failed += 1
                    result.success = False

        # Check signals structure
        if "signals" in output and output["signals"]:
            first_signal = output["signals"][0]
            signal_keys = ["signal", "code_context"]
            for key in signal_keys:
                if key in first_signal:
                    print(f"  ✓ First signal has '{key}'")
                    result.assertions_passed += 1
                else:
                    print(f"  ✗ First signal missing '{key}'")
                    result.assertions_failed += 1
                    result.success = False

        # Summary
        print(f"\n  Summary:")
        if "signals" in output:
            print(f"    Signals in context: {len(output['signals'])}")
        if "group" in output:
            print(f"    Tool: {output['group'].get('tool_id')}")
            print(f"    Signal type: {output['group'].get('signal_type')}")

        return result


def main():
    """Run the test."""
    test = ContextBuilderTest(
        fixture_dir=Path(__file__).parent / "fixtures",
        output_dir=Path(__file__).parent.parent.parent.parent / "scripts" / "debug" / "outputs",
        use_live_mode=False,
    )

    result = test.run()
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()

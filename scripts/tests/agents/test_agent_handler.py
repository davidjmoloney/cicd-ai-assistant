#!/usr/bin/env python3
"""
Test script for AgentHandler (LLM fix generation).

Usage:
    # Fixture mode (no API calls)
    MAKE_LLM_CALL=false PYTHONPATH=src python scripts/tests/agents/test_agent_handler.py

    # Live mode (requires API key)
    MAKE_LLM_CALL=true PYTHONPATH=src python scripts/tests/agents/test_agent_handler.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.test_base import BaseTest, TestResult
from agents.agent_handler import AgentHandler, FixPlan


class AgentHandlerTest(BaseTest[dict, FixPlan]):
    """Test agent handler."""

    def load_input(self) -> dict:
        """Load context input."""
        return self.load_fixture("context_input.json")

    def run_component(self, input_data: dict) -> FixPlan:
        """Run agent handler."""
        if self.use_live_mode:
            # Make live LLM call
            handler = AgentHandler(provider="openai")
            result = handler.generate_fix_plan(input_data)
            if not result.success:
                raise RuntimeError(f"Agent failed: {result.error}")
            return result.fix_plan
        else:
            # Load from fixture
            fix_plan_data = self.load_fixture("fixplan_expected.json")
            return FixPlan.from_dict(fix_plan_data)

    def validate_output(self, output: FixPlan) -> TestResult[FixPlan]:
        """Validate fix plan."""
        result = TestResult(success=True, output=output)

        # Check required fields
        if self.assert_not_empty(output.summary, "Has summary"):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        if self.assert_not_empty(output.file_edits, "Has file_edits"):
            result.assertions_passed += 1
        else:
            result.assertions_failed += 1
            result.success = False

        # Summary
        print(f"\n  Summary: {output.summary}")
        print(f"  Confidence: {output.confidence}")
        print(f"  File edits: {len(output.file_edits)}")

        return result


def main():
    """Run the test."""
    from common.test_config import TestConfig
    config = TestConfig()

    test = AgentHandlerTest(
        fixture_dir=Path(__file__).parent / "fixtures",
        output_dir=Path(__file__).parent.parent.parent.parent / "scripts" / "debug" / "outputs",
        use_live_mode=config.make_llm_call,
    )

    result = test.run()
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()

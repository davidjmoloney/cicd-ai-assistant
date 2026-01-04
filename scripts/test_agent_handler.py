#!/usr/bin/env python3
"""
Simple test script for the agent handler.

Usage:
    PYTHONPATH=src python scripts/test_agent_handler.py
"""
import json
import sys
from pathlib import Path

from agents.agent_handler import AgentHandler

CONTEXT_FILE = Path(__file__).parent / "context_output.json"


def main():
    # Check API key is set
    from agents.llm_provider import OPENAI_API_KEY
    if not OPENAI_API_KEY:
        print("ERROR: OPENAI_API_KEY environment variable not set")
        sys.exit(1)
    print("API key configured")

    # Load context
    print(f"Loading context from {CONTEXT_FILE}")
    with open(CONTEXT_FILE) as f:
        context = json.load(f)
    print(f"Loaded {context['group']['group_size']} signals")

    # Call agent
    print("\nCalling OpenAI...")
    handler = AgentHandler(provider="openai")
    result = handler.generate_fix_plan(context)

    # Print result
    if result.success:
        print("\nSUCCESS!")
        print(f"Summary: {result.fix_plan.summary}")
        print(f"Confidence: {result.fix_plan.confidence}")
        print(f"Files to edit: {len(result.fix_plan.file_edits)}")

        for fe in result.fix_plan.file_edits:
            print(f"\n  {fe.file_path}:")
            for edit in fe.edits:
                print(f"    - {edit.description} ({edit.edit_type.value} at row {edit.span.start.row})")

        # Also dump full JSON
        print("\n--- Full Fix Plan JSON ---")
        print(json.dumps(result.fix_plan.to_dict(), indent=2))
    else:
        print(f"\nFAILED: {result.error}")
        if result.llm_response:
            print(f"Raw response: {result.llm_response.content[:500]}")


if __name__ == "__main__":
    main()

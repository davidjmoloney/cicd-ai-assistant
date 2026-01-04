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
    # Check API key is set (try Anthropic first, fall back to OpenAI)
    from agents.llm_provider import ANTHROPIC_API_KEY, OPENAI_API_KEY

    if ANTHROPIC_API_KEY:
        provider = "anthropic"
        print("Using Anthropic/Claude")
    elif OPENAI_API_KEY:
        provider = "openai"
        print("Using OpenAI")
    else:
        print("ERROR: Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable")
        sys.exit(1)

    # Load context
    print(f"Loading context from {CONTEXT_FILE}")
    with open(CONTEXT_FILE) as f:
        context = json.load(f)
    print(f"Loaded {context['group']['group_size']} signals")

    # Call agent
    print(f"\nCalling {provider}...")
    handler = AgentHandler(provider=provider)
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

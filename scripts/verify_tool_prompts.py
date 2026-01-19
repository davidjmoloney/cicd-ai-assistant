#!/usr/bin/env python3
"""
Verification script for tool-specific prompts.

This script demonstrates and tests the tool-specific prompting system.
Run this to verify that different tools get different guidance.

Usage:
    python scripts/verify_tool_prompts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agents.tool_prompts import (
    get_system_prompt,
    list_supported_tools,
    BASE_SYSTEM_PROMPT,
)


def main() -> int:
    print("=" * 80)
    print("Tool-Specific Prompt Verification")
    print("=" * 80)
    print()

    # List supported tools
    supported = list_supported_tools()
    print(f"✅ Supported tools: {', '.join(supported)}")
    print()

    # Test base prompt
    print("📝 Base Prompt Length:", len(BASE_SYSTEM_PROMPT), "characters")
    print()

    # Test each tool-specific prompt
    tools_to_test = ["mypy", "ruff", "bandit", "unknown-tool"]

    for tool in tools_to_test:
        prompt = get_system_prompt(tool)

        # Check if it's just base or has tool-specific guidance
        has_tool_guidance = len(prompt) > len(BASE_SYSTEM_PROMPT)

        print(f"🔧 Tool: {tool}")
        print(f"   Prompt length: {len(prompt):,} characters")
        print(f"   Has tool-specific guidance: {'✅ Yes' if has_tool_guidance else '❌ No (fallback to base)'}")

        # Show a snippet of tool-specific guidance
        if has_tool_guidance:
            # Extract tool-specific part
            tool_part = prompt[len(BASE_SYSTEM_PROMPT):].strip()
            lines = tool_part.split('\n')
            # Show first few non-empty lines
            preview_lines = [line for line in lines[:5] if line.strip()]
            if preview_lines:
                print(f"   Preview: {preview_lines[0][:60]}...")
        print()

    # Verify mypy has validation guidance
    mypy_prompt = get_system_prompt("mypy")
    critical_phrases = [
        "validation",
        "NEVER bypass",
        "preserve",
    ]

    print("-" * 80)
    print("✅ Critical MyPy Guidance Checks")
    print("-" * 80)
    for phrase in critical_phrases:
        found = phrase.lower() in mypy_prompt.lower()
        status = "✅" if found else "❌"
        print(f"{status} Contains '{phrase}': {found}")
    print()

    # Verify bandit has security warnings
    bandit_prompt = get_system_prompt("bandit")
    security_phrases = [
        "security",
        "CRITICAL",
        "vulnerability",
    ]

    print("-" * 80)
    print("✅ Critical Bandit Guidance Checks")
    print("-" * 80)
    for phrase in security_phrases:
        found = phrase.lower() in bandit_prompt.lower()
        status = "✅" if found else "❌"
        print(f"{status} Contains '{phrase}': {found}")
    print()

    print("=" * 80)
    print("✅ Verification Complete!")
    print("=" * 80)
    print()
    print("Next steps:")
    print("1. Review the prompts in: src/agents/tool_prompts.py")
    print("2. Run your test with: python scripts/test_mypy.py")
    print("3. Compare fix quality with previous results")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

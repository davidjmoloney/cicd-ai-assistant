#!/usr/bin/env python3
"""
Simple debug script for tracing data flow through pr_generator module.
"""
import json
from pathlib import Path

# Add src to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agents.agent_handler import FixPlan
from github.pr_generator import apply_edits_to_content

# Config
AGENT_OUTPUT = Path(__file__).parent / "agent_output.json"
DEBUG_OUTPUT = Path(__file__).parent / "debug_output.txt"

# Mock file content (simulates the target file)
MOCK_FILE_LINES = 500
def get_mock_content():
    lines = []
    for i in range(1, MOCK_FILE_LINES + 1):
        if i == 8:
            lines.append("import re")
        elif i == 11:
            lines.append("from pathlib import Path") 
        elif i == 494:
            lines.append('                print(f"🔍 Step 1: Analyzing user prompt")')
        else:
            lines.append(f"# Line {i}")
    return "\n".join(lines)


def main():
    print("=" * 60)
    print("PR Generator Debug Script")
    print("=" * 60)

    # 1. Load fix plan
    print("\n[1] Loading agent_output.json...")
    with open(AGENT_OUTPUT) as f:
        fix_plan = FixPlan.from_dict(json.load(f))

    print(f"    Tool: {fix_plan.group_tool_id}")
    print(f"    File edits: {len(fix_plan.file_edits)}")

    # 2. Show each FileEdit
    print("\n[2] FileEdit details:")
    for i, fe in enumerate(fix_plan.file_edits):
        print(f"\n    FileEdit #{i+1}: {fe.file_path}")
        print(f"    Reasoning: {fe.reasoning[:50]}...")
        for j, edit in enumerate(fe.edits):
            print(f"      Edit #{j+1}: {edit.edit_type.value}")
            print(f"        Span: row {edit.span.start.row}:{edit.span.start.column} -> {edit.span.end.row}:{edit.span.end.column}")
            print(f"        Content: {repr(edit.content)}")
            print(f"        Description: {edit.description}")

    # 3. Apply edits to mock content
    print("\n[3] Applying edits to mock content...")
    mock_content_r1 = get_mock_content()
    test_file = Path(__file__).parent / f"debug_test_context.txt"
    with open(test_file, "w") as f:
            f.write(mock_content_r1)
    print(f"    Original lines: {len(mock_content_r1.splitlines())}")


    # Show original lines around edit locations
    lines = mock_content_r1.splitlines()
    print("\n    Original content at edit locations:")
    for row in [8, 11, 494]:
        if row <= len(lines):
            print(f"      Line {row}: {repr(lines[row-1])}")

    # Apply each FileEdit separately (as pr_generator does)
    print("\n[4] Applying each FileEdit separately:")
    for i, fe in enumerate(fix_plan.file_edits):
        result = apply_edits_to_content(mock_content_r1, fe.edits)
        result_lines = result.splitlines()
        print(f"\n    After FileEdit #{i+1}:")
        print(f"      Lines changed: {len(mock_content_r1.splitlines())} -> {len(result_lines)}")

        # Show diff at edit location
        edit = fe.edits[0]
        row = edit.span.start.row
        if row <= len(result_lines):
            print(f"      Line {row} now: {repr(result_lines[row-1])}")

        # Write result to file for inspection
        output_file = Path(__file__).parent / f"debug_fileedit_{i+1}.txt"
        with open(output_file, "w") as f:
            f.write(result)
        print(f"      Written to: {output_file.name}")

    # 5. Apply ALL edits combined (what should happen)
    print("\n[5] Applying ALL edits combined:")
    all_edits = []
    for fe in fix_plan.file_edits:
        all_edits.extend(fe.edits)
    
    mock_content_r2 = get_mock_content()
    combined_result = apply_edits_to_content(mock_content_r2, all_edits)
    combined_lines = combined_result.splitlines()
    print(f"    Lines: {len(mock_content_r2.splitlines())} -> {len(combined_lines)}")

    # Show results at edit locations
    print("\n    Content at edit locations after ALL edits:")
    for row in [8, 11, 494]:
        # Adjust for deleted lines
        adjusted_row = row
        if row > 8:
            adjusted_row -= 1  # Line 8 deleted
        if row > 11:
            adjusted_row -= 1  # Line 11 deleted
        if adjusted_row <= len(combined_lines):
            print(f"      Original line {row} (now {adjusted_row}): {repr(combined_lines[adjusted_row-1])}")

    output_file = Path(__file__).parent / "debug_combined.txt"
    with open(output_file, "w") as f:
        f.write(combined_result)
    print(f"\n    Written to: {output_file.name}")

    

    print("\n" + "=" * 60)
    print("Debug complete! Check debug_*.txt files for results.")
    print("=" * 60)


if __name__ == "__main__":
    main()

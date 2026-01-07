#!/usr/bin/env python3
"""
Debug script for tracing data flow through the pr_generator module.

This script helps identify issues with:
- File edit parsing from agent_output.json
- Row/column span interpretation (0-indexed vs 1-indexed)
- Content transformation at each step
- Off-by-one errors in line/column indexing

Usage:
    python scripts/debug_pr_generator.py

Requirements:
    - Set GITHUB_TOKEN environment variable (or use placeholder for local testing)
    - Ensure agent_output.json exists in scripts/ directory
"""

import json
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


# =============================================================================
# Configuration
# =============================================================================

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "placeholder_token")
REPO_OWNER = "your-org"
REPO_NAME = "your-repo"
BASE_BRANCH = "main"

# Path to agent output with file edits
SCRIPT_DIR = Path(__file__).parent
AGENT_OUTPUT_PATH = SCRIPT_DIR / "agent_output.json"

# Debug output directory
DEBUG_OUTPUT_DIR = SCRIPT_DIR / "debug_output"


# =============================================================================
# Data classes for structured debugging
# =============================================================================

@dataclass
class Span:
    """Represents a text span with start/end positions."""
    start_row: int
    start_col: int
    end_row: int
    end_col: int

    def __str__(self):
        return f"({self.start_row}:{self.start_col}) -> ({self.end_row}:{self.end_col})"

    def as_0_indexed(self):
        """Convert to 0-indexed (assuming input is 1-indexed)."""
        return Span(
            self.start_row - 1,
            self.start_col - 1,
            self.end_row - 1,
            self.end_col - 1
        )

    def as_1_indexed(self):
        """Convert to 1-indexed (assuming input is 0-indexed)."""
        return Span(
            self.start_row + 1,
            self.start_col + 1,
            self.end_row + 1,
            self.end_col + 1
        )


@dataclass
class Edit:
    """Represents a single edit operation."""
    edit_type: str
    span: Span
    content: str
    description: str


@dataclass
class FileEdit:
    """Represents all edits for a single file."""
    file_path: str
    reasoning: str
    edits: list[Edit]


# =============================================================================
# Parsing functions
# =============================================================================

def parse_span(span_dict: dict) -> Span:
    """Parse a span from JSON format."""
    return Span(
        start_row=span_dict["start"]["row"],
        start_col=span_dict["start"]["column"],
        end_row=span_dict["end"]["row"],
        end_col=span_dict["end"]["column"]
    )


def parse_edit(edit_dict: dict) -> Edit:
    """Parse an edit from JSON format."""
    return Edit(
        edit_type=edit_dict["edit_type"],
        span=parse_span(edit_dict["span"]),
        content=edit_dict.get("content", ""),
        description=edit_dict.get("description", "")
    )


def parse_file_edit(file_edit_dict: dict) -> FileEdit:
    """Parse a file edit from JSON format."""
    return FileEdit(
        file_path=file_edit_dict["file_path"],
        reasoning=file_edit_dict.get("reasoning", ""),
        edits=[parse_edit(e) for e in file_edit_dict["edits"]]
    )


def load_agent_output(path: Path) -> dict:
    """Load and parse the agent output JSON."""
    with open(path, "r") as f:
        return json.load(f)


# =============================================================================
# Debug output functions
# =============================================================================

def print_separator(title: str = "", char: str = "=", width: int = 80):
    """Print a visual separator."""
    if title:
        padding = (width - len(title) - 2) // 2
        print(f"{char * padding} {title} {char * padding}")
    else:
        print(char * width)


def debug_print_span_info(span: Span, prefix: str = ""):
    """Print detailed span information."""
    print(f"{prefix}Original span: {span}")
    print(f"{prefix}As 0-indexed:  {span.as_0_indexed()}")
    print(f"{prefix}As 1-indexed:  {span.as_1_indexed()}")


def debug_print_file_edit(file_edit: FileEdit, index: int):
    """Print detailed file edit information."""
    print_separator(f"File Edit #{index + 1}")
    print(f"File: {file_edit.file_path}")
    print(f"Reasoning: {file_edit.reasoning}")
    print(f"Number of edits: {len(file_edit.edits)}")
    print()

    for i, edit in enumerate(file_edit.edits):
        print(f"  Edit #{i + 1}:")
        print(f"    Type: {edit.edit_type}")
        print(f"    Description: {edit.description}")
        print(f"    Content: {repr(edit.content)}")
        debug_print_span_info(edit.span, prefix="    ")
        print()


# =============================================================================
# Content transformation debugging
# =============================================================================

def get_mock_file_content() -> str:
    """
    Returns mock file content for testing.
    Replace this with actual file content loading in your implementation.

    This mock represents a Python file structure similar to what the
    agent_output.json edits target.
    """
    # Create a mock file with line numbers matching the agent_output.json
    lines = []
    for i in range(1, 510):
        if i == 8:
            lines.append("import re")
        elif i == 11:
            lines.append("from pathlib import Path")
        elif i == 494:
            lines.append('        print(f"🔍 Step 1: Analyzing user prompt")')
        else:
            lines.append(f"# Line {i}: placeholder content")
    return "\n".join(lines)


def apply_edit_debug(
    content: str,
    edit: Edit,
    indexing: str = "1-indexed",
    debug_file: Optional[Path] = None
) -> tuple[str, dict]:
    """
    Apply a single edit to content with detailed debugging.

    Args:
        content: The file content to edit
        edit: The edit to apply
        indexing: Either "0-indexed" or "1-indexed"
        debug_file: Optional path to write debug info

    Returns:
        Tuple of (new_content, debug_info_dict)
    """
    lines = content.split("\n")
    debug_info = {
        "indexing_mode": indexing,
        "total_lines": len(lines),
        "edit_type": edit.edit_type,
        "original_span": str(edit.span),
    }

    # Adjust span based on indexing mode
    if indexing == "1-indexed":
        # Convert 1-indexed to 0-indexed for list operations
        start_row = edit.span.start_row - 1
        start_col = edit.span.start_col - 1
        end_row = edit.span.end_row - 1
        end_col = edit.span.end_col - 1
    else:
        start_row = edit.span.start_row
        start_col = edit.span.start_col
        end_row = edit.span.end_row
        end_col = edit.span.end_col

    debug_info["adjusted_span"] = f"({start_row}:{start_col}) -> ({end_row}:{end_col})"

    # Bounds checking
    if start_row < 0 or start_row >= len(lines):
        debug_info["error"] = f"start_row {start_row} out of bounds (0-{len(lines)-1})"
        return content, debug_info

    if end_row < 0 or end_row >= len(lines):
        debug_info["error"] = f"end_row {end_row} out of bounds (0-{len(lines)-1})"
        return content, debug_info

    # Capture context around the edit
    context_before = max(0, start_row - 2)
    context_after = min(len(lines), end_row + 3)

    debug_info["context_lines_before"] = {
        i + 1: lines[i] for i in range(context_before, start_row)
    }
    debug_info["affected_lines"] = {
        i + 1: lines[i] for i in range(start_row, end_row + 1)
    }
    debug_info["context_lines_after"] = {
        i + 1: lines[i] for i in range(end_row + 1, context_after)
    }

    # Apply the edit
    if edit.edit_type == "delete":
        # Delete spans the entire line(s)
        if start_col == 0 and end_col == 0:
            # Delete complete lines (end_col=0 means start of next line)
            debug_info["delete_mode"] = "full_lines"
            debug_info["lines_deleted"] = list(range(start_row + 1, end_row + 1))
            new_lines = lines[:start_row] + lines[end_row:]
        else:
            # Delete within lines
            debug_info["delete_mode"] = "partial"
            if start_row == end_row:
                line = lines[start_row]
                new_line = line[:start_col] + line[end_col:]
                new_lines = lines[:start_row] + [new_line] + lines[start_row + 1:]
                debug_info["original_line"] = line
                debug_info["modified_line"] = new_line
            else:
                # Multi-line partial delete
                first_line = lines[start_row][:start_col]
                last_line = lines[end_row][end_col:]
                new_line = first_line + last_line
                new_lines = lines[:start_row] + [new_line] + lines[end_row + 1:]
                debug_info["merged_line"] = new_line

    elif edit.edit_type == "replace":
        debug_info["replacement_content"] = edit.content

        if start_row == end_row:
            # Single line replacement
            line = lines[start_row]
            debug_info["original_line"] = line
            debug_info["original_segment"] = line[start_col:end_col]

            new_line = line[:start_col] + edit.content + line[end_col:]
            debug_info["modified_line"] = new_line

            new_lines = lines[:start_row] + [new_line] + lines[start_row + 1:]
        else:
            # Multi-line replacement
            first_part = lines[start_row][:start_col]
            last_part = lines[end_row][end_col:]
            new_line = first_part + edit.content + last_part
            new_lines = lines[:start_row] + [new_line] + lines[end_row + 1:]
            debug_info["merged_line"] = new_line

    elif edit.edit_type == "insert":
        line = lines[start_row]
        new_line = line[:start_col] + edit.content + line[start_col:]
        new_lines = lines[:start_row] + [new_line] + lines[start_row + 1:]
        debug_info["modified_line"] = new_line

    else:
        debug_info["error"] = f"Unknown edit type: {edit.edit_type}"
        return content, debug_info

    new_content = "\n".join(new_lines)
    debug_info["lines_after_edit"] = len(new_lines)

    # Write debug info to file if requested
    if debug_file:
        with open(debug_file, "w") as f:
            f.write(json.dumps(debug_info, indent=2))
            f.write("\n\n--- NEW CONTENT ---\n")
            f.write(new_content)

    return new_content, debug_info


def compare_indexing_modes(content: str, edit: Edit) -> dict:
    """
    Apply edit with both 0-indexed and 1-indexed modes and compare results.

    This helps identify off-by-one errors.
    """
    result_0, debug_0 = apply_edit_debug(content, edit, "0-indexed")
    result_1, debug_1 = apply_edit_debug(content, edit, "1-indexed")

    return {
        "0_indexed_result": {
            "debug": debug_0,
            "content_preview": result_0[:500] + "..." if len(result_0) > 500 else result_0,
        },
        "1_indexed_result": {
            "debug": debug_1,
            "content_preview": result_1[:500] + "..." if len(result_1) > 500 else result_1,
        },
        "results_match": result_0 == result_1,
    }


# =============================================================================
# Main debugging workflow
# =============================================================================

def run_debug_workflow():
    """Main debugging workflow."""
    print_separator("PR Generator Debug Script")
    print()

    # Create debug output directory
    DEBUG_OUTPUT_DIR.mkdir(exist_ok=True)

    # Step 1: Load and parse agent output
    print_separator("Step 1: Loading Agent Output")
    if not AGENT_OUTPUT_PATH.exists():
        print(f"ERROR: Agent output not found at {AGENT_OUTPUT_PATH}")
        return

    agent_output = load_agent_output(AGENT_OUTPUT_PATH)
    print(f"Loaded agent output from: {AGENT_OUTPUT_PATH}")
    print(f"Tool ID: {agent_output.get('group_tool_id')}")
    print(f"Signal Type: {agent_output.get('group_signal_type')}")
    print(f"Number of file edits: {len(agent_output.get('file_edits', []))}")
    print()

    # Step 2: Parse file edits
    print_separator("Step 2: Parsing File Edits")
    file_edits = [parse_file_edit(fe) for fe in agent_output.get("file_edits", [])]

    for i, file_edit in enumerate(file_edits):
        debug_print_file_edit(file_edit, i)

    # Step 3: Test edit application
    print_separator("Step 3: Testing Edit Application")
    mock_content = get_mock_file_content()
    print(f"Mock file has {len(mock_content.splitlines())} lines")
    print()

    # Apply each edit and compare indexing modes
    for i, file_edit in enumerate(file_edits):
        for j, edit in enumerate(file_edit.edits):
            edit_id = f"file{i}_edit{j}"
            print(f"\nProcessing {edit_id}: {edit.description}")

            # Write comparison to file
            comparison = compare_indexing_modes(mock_content, edit)
            comparison_file = DEBUG_OUTPUT_DIR / f"{edit_id}_comparison.json"
            with open(comparison_file, "w") as f:
                json.dump(comparison, f, indent=2, default=str)
            print(f"  Comparison written to: {comparison_file}")
            print(f"  Results match between 0-indexed and 1-indexed: {comparison['results_match']}")

            # Apply with 1-indexed (typical for editor/LSP spans) and save
            new_content, debug_info = apply_edit_debug(
                mock_content,
                edit,
                indexing="1-indexed",
                debug_file=DEBUG_OUTPUT_DIR / f"{edit_id}_result.txt"
            )

            if "error" in debug_info:
                print(f"  ERROR: {debug_info['error']}")
            else:
                print(f"  Edit applied successfully")
                if "original_line" in debug_info:
                    print(f"    Original: {debug_info['original_line']}")
                if "modified_line" in debug_info:
                    print(f"    Modified: {debug_info['modified_line']}")
                if "lines_deleted" in debug_info:
                    print(f"    Lines deleted: {debug_info['lines_deleted']}")

    # Step 4: Test cumulative edits
    print_separator("Step 4: Testing Cumulative Edits")
    print("Applying all edits in sequence to test interaction...")

    cumulative_content = mock_content
    cumulative_debug = []

    # Group edits by file and sort by line number (descending to avoid offset issues)
    all_edits = []
    for file_edit in file_edits:
        for edit in file_edit.edits:
            all_edits.append((file_edit.file_path, edit))

    # Sort by start row descending (apply from bottom to top to avoid offset shifts)
    all_edits.sort(key=lambda x: x[1].span.start_row, reverse=True)

    print(f"\nEdit application order (bottom to top):")
    for file_path, edit in all_edits:
        print(f"  Line {edit.span.start_row}: {edit.edit_type} - {edit.description}")

    print("\nApplying edits...")
    for file_path, edit in all_edits:
        cumulative_content, debug_info = apply_edit_debug(
            cumulative_content,
            edit,
            indexing="1-indexed"
        )
        cumulative_debug.append({
            "edit": edit.description,
            "debug": debug_info
        })

        if "error" in debug_info:
            print(f"  ERROR at line {edit.span.start_row}: {debug_info['error']}")
        else:
            print(f"  Applied: {edit.description}")

    # Write cumulative result
    cumulative_file = DEBUG_OUTPUT_DIR / "cumulative_result.txt"
    with open(cumulative_file, "w") as f:
        f.write(cumulative_content)
    print(f"\nCumulative result written to: {cumulative_file}")

    cumulative_debug_file = DEBUG_OUTPUT_DIR / "cumulative_debug.json"
    with open(cumulative_debug_file, "w") as f:
        json.dump(cumulative_debug, f, indent=2, default=str)
    print(f"Cumulative debug info written to: {cumulative_debug_file}")

    # Summary
    print_separator("Summary")
    print(f"Debug output directory: {DEBUG_OUTPUT_DIR}")
    print(f"Files generated:")
    for f in sorted(DEBUG_OUTPUT_DIR.iterdir()):
        print(f"  - {f.name}")

    print("\n" + "=" * 80)
    print("Debug workflow complete!")
    print("=" * 80)
    print("\nNext steps:")
    print("1. Check the debug_output/ directory for detailed results")
    print("2. Compare *_comparison.json files to see if indexing mode matters")
    print("3. Review *_result.txt files to see exactly what content would be produced")
    print("4. Look at cumulative_result.txt to see final state after all edits")
    print("5. Use this info to trace issues in your actual PRGenerator implementation")


# =============================================================================
# Hook for PRGenerator integration
# =============================================================================

def create_debug_hooks():
    """
    Returns hook functions that can be integrated into PRGenerator
    to capture data at key points.

    Example usage in PRGenerator:

        from scripts.debug_pr_generator import create_debug_hooks

        hooks = create_debug_hooks()

        class PRGenerator:
            def _commit_file_edit(self, file_path, new_content):
                hooks['before_commit'](file_path, new_content)
                # ... existing logic ...
                hooks['after_commit'](file_path, result)
    """
    debug_data = {"calls": []}

    def before_commit(file_path: str, new_content: str):
        """Hook to call before committing a file edit."""
        call_data = {
            "event": "before_commit",
            "file_path": file_path,
            "content_length": len(new_content),
            "content_lines": len(new_content.splitlines()),
            "content_preview": new_content[:1000],
        }
        debug_data["calls"].append(call_data)

        # Write to file for inspection
        debug_file = DEBUG_OUTPUT_DIR / f"commit_{len(debug_data['calls'])}_before.txt"
        DEBUG_OUTPUT_DIR.mkdir(exist_ok=True)
        with open(debug_file, "w") as f:
            f.write(f"File: {file_path}\n")
            f.write(f"Content length: {len(new_content)}\n")
            f.write(f"Lines: {len(new_content.splitlines())}\n")
            f.write("=" * 80 + "\n")
            f.write(new_content)
        print(f"[DEBUG] before_commit logged to: {debug_file}")

    def after_commit(file_path: str, result: dict):
        """Hook to call after committing a file edit."""
        call_data = {
            "event": "after_commit",
            "file_path": file_path,
            "result": result,
        }
        debug_data["calls"].append(call_data)
        print(f"[DEBUG] after_commit: {file_path} -> {result}")

    def get_all_data():
        """Get all captured debug data."""
        return debug_data

    return {
        "before_commit": before_commit,
        "after_commit": after_commit,
        "get_all_data": get_all_data,
    }


if __name__ == "__main__":
    run_debug_workflow()

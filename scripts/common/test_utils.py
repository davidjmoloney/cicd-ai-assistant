"""Shared utility functions for test scripts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(file_path: Path) -> Any:
    """
    Load JSON from file.

    Args:
        file_path: Path to JSON file

    Returns:
        Parsed JSON data

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file contains invalid JSON
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: Any, file_path: Path, *, indent: int = 2) -> None:
    """
    Save data as JSON to file.

    Args:
        data: Data to save (must be JSON-serializable)
        file_path: Path to output file
        indent: JSON indentation level (default: 2)
    """
    # Ensure parent directory exists
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, default=str)


def compare_dicts(actual: dict, expected: dict, path: str = "") -> list[str]:
    """
    Recursively compare two dictionaries and return list of differences.

    Args:
        actual: Actual dictionary
        expected: Expected dictionary
        path: Current path in the dictionary (for error messages)

    Returns:
        List of difference descriptions. Empty list if equal.
    """
    differences = []

    # Check for keys in expected but not in actual
    for key in expected:
        current_path = f"{path}.{key}" if path else key
        if key not in actual:
            differences.append(f"Missing key: {current_path}")
        else:
            # Recursively compare nested dicts
            if isinstance(expected[key], dict) and isinstance(actual[key], dict):
                differences.extend(
                    compare_dicts(actual[key], expected[key], current_path)
                )
            # Compare lists
            elif isinstance(expected[key], list) and isinstance(actual[key], list):
                if len(expected[key]) != len(actual[key]):
                    differences.append(
                        f"{current_path}: List length mismatch "
                        f"(expected {len(expected[key])}, got {len(actual[key])})"
                    )
            # Compare values
            elif expected[key] != actual[key]:
                differences.append(
                    f"{current_path}: Value mismatch "
                    f"(expected {expected[key]}, got {actual[key]})"
                )

    # Check for keys in actual but not in expected
    for key in actual:
        current_path = f"{path}.{key}" if path else key
        if key not in expected:
            differences.append(f"Unexpected key: {current_path}")

    return differences


def print_section_header(title: str, width: int = 80) -> None:
    """
    Print a formatted section header.

    Args:
        title: Section title
        width: Header width (default: 80)
    """
    print()
    print("=" * width)
    print(title)
    print("=" * width)


def print_subsection_header(title: str, width: int = 80) -> None:
    """
    Print a formatted subsection header.

    Args:
        title: Subsection title
        width: Header width (default: 80)
    """
    print()
    print("-" * width)
    print(title)
    print("-" * width)


def format_file_path(path: Path, base_dir: Path | None = None) -> str:
    """
    Format file path for display, optionally relative to base directory.

    Args:
        path: File path to format
        base_dir: Base directory to make path relative to (optional)

    Returns:
        Formatted path string
    """
    if base_dir:
        try:
            return str(path.relative_to(base_dir))
        except ValueError:
            # Path is not relative to base_dir
            pass
    return str(path)

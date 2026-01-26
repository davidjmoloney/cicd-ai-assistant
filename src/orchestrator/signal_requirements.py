# orchestrator/edit_window_config.py
"""
Configuration for signal-specific context and edit windows.

This module defines what context is needed and what edit window size/type
should be used for each signal type and rule code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from signals.models import FixSignal


EditWindowType = Literal["lines", "function", "class", "imports", "try_except"]


@dataclass(frozen=True)
class EditWindowSpec:
    """
    Specification for how to build an edit window for a signal.

    Attributes:
        window_type: Type of edit window ('lines', 'function', 'class', 'imports', 'try_except')
        lines: Number of lines on each side (only used if window_type='lines')
        min_context_lines: Minimum context window size (default 10)
        min_edit_lines: Minimum edit window size (default 2)
    """
    window_type: EditWindowType
    lines: int = 0  # Only used for window_type='lines'
    min_context_lines: int = 10  # Minimum ± lines for context window
    min_edit_lines: int = 2  # Minimum ± lines for edit window


def get_edit_window_spec(signal: FixSignal) -> EditWindowSpec:
    """
    Get the appropriate edit window specification for a signal.

    Based on the signal's tool_id (ruff, mypy) and rule_code, determines:
    - What type of edit window to use (lines, function, imports, try_except)
    - How many lines to include (if using line-based window)
    - Minimum context and edit window sizes

    Args:
        signal: The FixSignal to determine edit window for

    Returns:
        EditWindowSpec with window_type and sizing information
    """
    rule_code = signal.rule_code or ""

    # ===================================================================
    # RUFF SIGNALS
    # ===================================================================

    # Import-related rules need full import block
    if rule_code in ["F401", "I001", "E402"]:
        return EditWindowSpec(window_type="imports")

    # Try/except-related rules need full try/except block
    if rule_code == "E722":  # Bare except
        return EditWindowSpec(window_type="try_except")

    # Function-level issues need full function
    if rule_code in ["F823"]:  # Local variable referenced before assignment
        return EditWindowSpec(window_type="function")

    # Trivial single-line fixes (±1 line)
    if rule_code in [
        "F541",  # f-string without placeholders
        "F901",  # raise NotImplemented
        "E711",  # comparison to None
        "E712",  # comparison to True/False
        "E721",  # type comparison
        "B007",  # unused loop variable
        "B011",  # assert False
        "B016",  # raise literal
    ]:
        return EditWindowSpec(window_type="lines", lines=1)

    # Small context fixes (±3 lines)
    if rule_code in [
        "F601",  # duplicate dict key
        "F841",  # unused variable
        "E731",  # lambda assignment
        "B006",  # mutable default arg
        "B015",  # useless comparison
    ]:
        return EditWindowSpec(window_type="lines", lines=3)

    # Medium context fixes (±5 lines)
    if rule_code in [
        "F811",  # redefinition
        "F821",  # undefined name
        "B002",  # unintentional self.attr
    ]:
        return EditWindowSpec(window_type="lines", lines=5)

    # ===================================================================
    # MYPY SIGNALS
    # ===================================================================

    # Function-level type issues need full function
    if rule_code in [
        "union-attr",    # Need to see type guards
        "return-value",  # Need to see full function signature and return
    ]:
        return EditWindowSpec(window_type="function")

    # Call-site type mismatches need broader context (±7 lines)
    if rule_code in [
        "arg-type",      # Argument type mismatch
        "call-arg",      # Unexpected/missing argument
        "attr-defined",  # Attribute not defined
    ]:
        return EditWindowSpec(window_type="lines", lines=7)

    # Assignment and operator issues need moderate context (±5 lines)
    if rule_code in [
        "assignment",    # Incompatible assignment
        "index",         # Invalid index type
        "operator",      # Unsupported operand types
        "name-defined",  # Name not defined
    ]:
        return EditWindowSpec(window_type="lines", lines=5)

    # ===================================================================
    # PYDOCSTYLE SIGNALS (DOCSTRING)
    # ===================================================================

    # D101: Missing docstring in public class - extract full class
    if rule_code == "D101":
        return EditWindowSpec(window_type="class")

    # D102: Missing docstring in public method - extract full method
    # D103: Missing docstring in public function - extract full function
    # For missing function/method docstrings, extract the full function/method
    # so the LLM can see the signature and generate an appropriate docstring
    if rule_code in ["D102", "D103"]:
        return EditWindowSpec(window_type="function")

    # ===================================================================
    # DEFAULT
    # ===================================================================

    # Default: ±7 lines for unknown rules
    return EditWindowSpec(window_type="lines", lines=7)


# ===================================================================
# ADDITIONAL CONTEXT REQUIREMENTS
# ===================================================================

@dataclass(frozen=True)
class ContextRequirements:
    """
    Additional context requirements beyond standard window/imports/function.

    Specifies what extra context to gather for specific signal types:
    - Class definition (for method-level type errors)
    - Type aliases (for mypy errors referencing custom types)
    - Related function definitions (for cross-function type flow)
    - Module-level constants (for validation logic understanding)
    - Function name to search for (if needs_related_functions is True)
    """
    needs_class_definition: bool = False
    needs_type_aliases: bool = False
    needs_related_functions: bool = False
    needs_module_constants: bool = False
    related_function_name: str | None = None


def get_context_requirements(signal: FixSignal) -> ContextRequirements:
    """
    Get additional context requirements for a signal.

    Determines what extra context beyond standard window/imports/function
    should be gathered based on the signal's rule code and error message.

    Args:
        signal: The FixSignal to determine context needs for

    Returns:
        ContextRequirements specifying what additional context to gather
    """
    rule_code = signal.rule_code or ""
    message = signal.message  # Keep original case for type detection
    message_lower = message.lower()

    # ===================================================================
    # MYPY TYPE ERRORS - Context Requirements
    # ===================================================================

    # Errors in methods/attributes often need class definition
    if rule_code in ["attr-defined", "override", "assignment"] and "self." in message_lower:
        return ContextRequirements(needs_class_definition=True)

    # Errors mentioning custom types need type aliases
    if rule_code in ["arg-type", "return-value", "assignment"]:
        # Check if error mentions likely custom types (CamelCase/PascalCase words)
        import re
        # Find potential type names (word characters starting with uppercase)
        potential_types = re.findall(r'\b[A-Z]\w+', message)
        # Filter out common non-type words
        common_words = {"Argument", "None", "Optional", "Union", "List", "Dict", "Tuple", "Type", "Missing", "Expected", "Incompatible"}
        custom_types = [t for t in potential_types if t not in common_words]
        if custom_types:
            return ContextRequirements(needs_type_aliases=True)

    # Call-site errors could benefit from function definition
    # But mypy error message includes signature, so only needed if unclear
    # For now, skip this as error messages are usually sufficient

    # ===================================================================
    # RUFF LINT ERRORS - Context Requirements
    # ===================================================================

    # Complexity warnings might benefit from seeing constants
    if rule_code == "C901":  # Too complex
        return ContextRequirements(needs_module_constants=True)

    # Undefined names need to check if it's a constant
    if rule_code == "F821":  # Undefined name
        return ContextRequirements(needs_module_constants=True)

    # ===================================================================
    # DEFAULT - No additional context needed
    # ===================================================================
    return ContextRequirements()

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
    if rule_code in ["F401", "I001", "I002", "E402"]:
        return EditWindowSpec(window_type="imports")

    # Try/except-related rules need full try/except block
    if rule_code in [
        "E722",  # bare except
        "B025",  # duplicate except handler
        "B029",  # except with empty tuple
        "S110",  # try-except-pass
        "S112",  # try-except-continue
    ]:
        return EditWindowSpec(window_type="try_except")

    # Function-level issues need full function
    if rule_code in [
        "F823",  # local variable referenced before assignment
        "B020",  # loop variable overrides iterator
        "B023",  # function uses loop variable (late binding closure)
    ]:
        return EditWindowSpec(window_type="function")

    # Class-level issues need full class
    if rule_code in [
        "B024",  # abstract class without abstract methods
    ]:
        return EditWindowSpec(window_type="class")

    # Trivial single-line fixes (±1 line)
    if rule_code in [
        # E/F-series
        "F541",  # f-string without placeholders
        "F901",  # raise NotImplemented
        "E711",  # comparison to None
        "E712",  # comparison to True/False
        "E721",  # type comparison
        # B-series
        "B007",  # unused loop variable
        "B009",  # getattr with constant attribute
        "B010",  # setattr with constant attribute
        "B011",  # assert False
        "B016",  # raise literal
        "B018",  # useless expression (no effect)
        "B028",  # warnings.warn without stacklevel
        "B032",  # unintentional type annotation (no assignment)
        # UP-series - all single-line modernizations
        "UP001", "UP003", "UP004",  # useless metaclass/type()/__class__/object inheritance
        "UP006", "UP007", "UP008",  # typing.List→list, Union→|, super()
        "UP009", "UP010", "UP012",  # utf-8 declaration, __future__, encode("utf-8")
        "UP015", "UP018",           # open mode "r", literal constructors
        "UP031", "UP032", "UP034",  # %-format, .format(), extraneous parens
        "UP035", "UP036", "UP037",  # deprecated typing import, version block, quoted annotation
        "UP038", "UP040",           # isinstance tuple→|, TypeAlias
        # S-series - single-statement security flags
        "S101",  # use of assert
        "S103",  # permissive chmod
        "S104",  # binding to 0.0.0.0
        "S108",  # insecure temp file/dir
        "S113",  # requests without timeout
        "S301",  # pickle usage
        "S311",  # pseudo-random generator
        "S501",  # requests verify=False
        "S506",  # unsafe yaml load
    ]:
        return EditWindowSpec(window_type="lines", lines=1)

    # Small context fixes (±3 lines)
    if rule_code in [
        # E/F-series
        "F601",  # duplicate dict key
        "F841",  # unused variable
        "E731",  # lambda assignment
        # B-series
        "B006",  # mutable default arg
        "B008",  # function call in default argument
        "B015",  # useless comparison
        "B017",  # assertRaises(Exception) too broad
        "B026",  # star-arg unpacking after keyword arg
        "B034",  # re.sub/split without flags= keyword
        "B039",  # mutable ContextVar default
        # S-series
        "S102",  # use of exec()
        "S105",  # hardcoded password in string
        "S106",  # hardcoded password in function argument
        "S107",  # hardcoded password in default value
        "S303",  # insecure hash function (MD5/SHA1)
        "S307",  # use of eval()
        "S324",  # insecure hash function (hashlib)
        "S602",  # subprocess with shell=True
        "S603",  # subprocess without shell
        "S605",  # starting process with a shell
        "S607",  # starting process with partial path
        "S701",  # jinja2 autoescape disabled
    ]:
        return EditWindowSpec(window_type="lines", lines=3)

    # Medium context fixes (±5 lines)
    if rule_code in [
        "F811",  # redefinition
        "F821",  # undefined name
        "B002",  # unary prefix increment (++x)
        "S608",  # SQL injection via string formatting
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

    # D101: Missing docstring in public class - just opening lines (±3)
    # D102: Missing docstring in public method - just opening lines (±3)
    # D103: Missing docstring in public function - just opening lines (±3)
    #
    # Strategy: Edit snippet contains ONLY the opening (signature + first few lines)
    #           Full function/class is sent as CONTEXT (read-only) so LLM understands
    #           what to document, but can only edit the opening to add docstring.
    #
    # This prevents LLM from "improving" the implementation while adding docstrings.
    if rule_code in ["D101", "D102", "D103"]:
        return EditWindowSpec(window_type="lines", lines=3)

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
    Context requirements for fixing a signal.

    Controls both BASE context (what's always considered) and ADDITIONAL context
    (signal-specific extras). This enables optimizing token usage by only sending
    relevant context for each signal type.

    BASE CONTEXT (sent with edit snippet):
        - include_imports: Import statements (for type definitions, dependencies)
        - include_enclosing_function: Full enclosing function/method (for call context)
        - include_try_except: Enclosing try/except block (for error handling context)

    ADDITIONAL CONTEXT (specialized requirements):
        - needs_class_definition: Class header with annotations (for method context)
        - needs_type_aliases: Type definitions like TypeVar, NewType, TypedDict (for type errors)
        - needs_related_functions: Related function definitions (for cross-function understanding)
        - needs_module_constants: Module-level UPPER_CASE constants (for validation logic)

    The goal is to minimize token usage while providing sufficient context:
    - Import errors need ONLY imports (not function bodies)
    - Docstring errors need ONLY the function/class to document (in edit snippet)
    - Type errors need imports + enclosing function
    - Bare except needs ONLY the try/except block
    """
    # Base context - control what standard context is included
    include_imports: bool = True
    include_enclosing_function: bool = True
    include_try_except: bool = False

    # Additional specialized context
    needs_class_definition: bool = False
    needs_type_aliases: bool = False
    needs_related_functions: bool = False
    needs_module_constants: bool = False
    related_function_name: str | None = None


def get_context_requirements(signal: FixSignal) -> ContextRequirements:
    """
    Get context requirements for a signal.

    Determines what context (both base and additional) should be gathered
    based on the signal's rule code and error message. This optimizes token
    usage by only sending relevant context for each signal type.

    Args:
        signal: The FixSignal to determine context needs for

    Returns:
        ContextRequirements specifying what context to gather
    """
    rule_code = signal.rule_code or ""
    message = signal.message  # Keep original case for type detection
    message_lower = message.lower()

    # ===================================================================
    # IMPORT ERRORS - Need ONLY imports
    # ===================================================================

    if rule_code in ["F401", "I001", "I002", "E402"]:
        # Import errors are global - don't need function context
        return ContextRequirements(
            include_imports=True,
            include_enclosing_function=False,
            include_try_except=False,
        )

    # ===================================================================
    # BARE EXCEPT - Need ONLY try/except block
    # ===================================================================

    if rule_code in [
        "E722",  # bare except
        "B025",  # duplicate except handler
        "B029",  # except with empty tuple
        "S110",  # try-except-pass
        "S112",  # try-except-continue
    ]:
        # Exception handling issues need only the try/except block
        return ContextRequirements(
            include_imports=False,
            include_enclosing_function=False,
            include_try_except=True,
        )

    # ===================================================================
    # DOCSTRING ERRORS - Need full function/class as context
    # ===================================================================

    # D101: Missing docstring in public class
    if rule_code == "D101":
        # Class docstring: extract full class as CONTEXT (via needs_class_definition)
        # Edit snippet is just opening lines (±3) where docstring will be added
        # Note: include_enclosing_function won't work for classes (looks for 'def', not 'class')
        return ContextRequirements(
            include_imports=True,
            include_enclosing_function=False,  # Classes don't have enclosing functions
            include_try_except=False,
            needs_class_definition=True,  # Full class as read-only context
        )

    # D102: Missing docstring in public method
    # D103: Missing docstring in public function
    if rule_code in ["D102", "D103"]:
        # Method/function docstring: extract full function as CONTEXT
        # Edit snippet is just opening lines (±3) where docstring will be added
        return ContextRequirements(
            include_imports=True,
            include_enclosing_function=True,  # Full method/function as read-only context
            include_try_except=False,
        )

    # ===================================================================
    # MYPY TYPE ERRORS - Need imports + enclosing function
    # ===================================================================

    # Function-level type issues (need to see all return paths, type guards)
    if rule_code in ["union-attr", "return-value"]:
        return ContextRequirements(
            include_imports=True,
            include_enclosing_function=True,
            include_try_except=False,
        )

    # Call-site type mismatches (need imports for types, function for context)
    if rule_code in ["arg-type", "call-arg"]:
        # Check if error mentions custom types
        import re
        potential_types = re.findall(r'\b[A-Z]\w+', message)
        common_words = {"Argument", "None", "Optional", "Union", "List", "Dict", "Tuple", "Type", "Missing", "Expected", "Incompatible"}
        custom_types = [t for t in potential_types if t not in common_words]

        return ContextRequirements(
            include_imports=True,
            include_enclosing_function=True,
            include_try_except=False,
            needs_type_aliases=bool(custom_types),  # Add type aliases if custom types detected
        )

    # Attribute errors in methods
    if rule_code in ["attr-defined", "override"] and "self." in message_lower:
        return ContextRequirements(
            include_imports=True,
            include_enclosing_function=True,
            include_try_except=False,
            needs_class_definition=True,  # Need class context for method errors
        )

    # Assignment type errors
    if rule_code == "assignment":
        # Check for custom types and self. references
        import re
        potential_types = re.findall(r'\b[A-Z]\w+', message)
        common_words = {"Argument", "None", "Optional", "Union", "List", "Dict", "Tuple", "Type", "Missing", "Expected", "Incompatible"}
        custom_types = [t for t in potential_types if t not in common_words]
        has_self = "self." in message_lower

        return ContextRequirements(
            include_imports=True,
            include_enclosing_function=True,
            include_try_except=False,
            needs_type_aliases=bool(custom_types),
            needs_class_definition=has_self,
        )

    # Other mypy errors (index, operator, name-defined)
    if rule_code in ["index", "operator", "name-defined"]:
        return ContextRequirements(
            include_imports=True,
            include_enclosing_function=True,
            include_try_except=False,
        )

    # ===================================================================
    # RUFF LINT ERRORS - Various requirements
    # ===================================================================

    # Function-level issues - local logic bugs, imports not relevant
    if rule_code in [
        "F823",  # local variable referenced before assignment
        "B020",  # loop variable overrides iterator
        "B023",  # function uses loop variable (late binding closure)
    ]:
        return ContextRequirements(
            include_imports=False,
            include_enclosing_function=True,
            include_try_except=False,
        )

    # Class-level issues - need class definition
    if rule_code == "B024":  # abstract class without abstract methods
        return ContextRequirements(
            include_imports=True,
            include_enclosing_function=False,
            include_try_except=False,
            needs_class_definition=True,
        )

    # Undefined names (might be a constant)
    if rule_code == "F821":
        return ContextRequirements(
            include_imports=True,  # Might need imports
            include_enclosing_function=True,
            include_try_except=False,
            needs_module_constants=True,  # Check if it's a missing constant
        )

    # Complexity warnings
    if rule_code == "C901":
        return ContextRequirements(
            include_imports=False,
            include_enclosing_function=True,
            include_try_except=False,
            needs_module_constants=True,
        )

    # ===================================================================
    # DEFAULT - Lenient context (when signal type is unknown)
    # ===================================================================

    # For unknown signals, be lenient: include imports + enclosing function
    # This ensures we have reasonable context even for unexpected signal types
    return ContextRequirements(
        include_imports=True,
        include_enclosing_function=True,
        include_try_except=False,
    )

# signals/policy/severity.py
from __future__ import annotations

from signals.models import Severity, SignalType

# v1: conservative, explicit, deterministic.
# You can improve later by using a config file (yaml/toml) with rule->severity.

# Ruff specifics:
# - Ruff rule prefixes don't perfectly equal severity, so don't pretend they do.
# - Start with a small mapping of *known safe autofix* rules to LOW/MEDIUM.
# - Everything else defaults to MEDIUM.

_RUFF_CODE_TO_SEVERITY: dict[str, Severity] = {
    # F-series: Pyflakes errors
    "F401": Severity.LOW,    # unused import - low risk, trivial fix
    "F541": Severity.LOW,    # extraneous f-string prefix - low risk, cosmetic
    "F601": Severity.HIGH,   # dictionary key repeated - duplicate keys cause data loss
    "F811": Severity.MEDIUM, # redefinition of unused name - can mask bugs
    "F821": Severity.HIGH,   # undefined name - runtime NameError
    "F823": Severity.HIGH,   # local variable referenced before assignment - runtime UnboundLocalError
    "F841": Severity.MEDIUM, # unused variable - semantics can be tricky; ruff marks fix unsafe often

    # E-series: PEP 8 style violations
    "E402": Severity.MEDIUM, # module level import not at top of file - can cause import order bugs
    "E701": Severity.LOW,    # multiple statements on one line (colon) - style issue
    "E702": Severity.LOW,    # multiple statements on one line (semicolon) - style issue
    "E713": Severity.LOW,    # test for membership should be 'not in' - style preference
    "E722": Severity.MEDIUM, # bare except - catches system exits and keyboard interrupts
    "E731": Severity.LOW,    # do not assign lambda, use def - readability preference
}

def severity_for_ruff(code: str) -> Severity:
    return _RUFF_CODE_TO_SEVERITY.get(code, Severity.MEDIUM)    # Return medium severity if code does not exist in dict definition 


# -------------------------------------------------------------------------
# PSEUDOCODE PLACEHOLDERS
# -------------------------------------------------------------------------


# MyPy error codes that indicate higher severity issues
# These are codes where type errors are more likely to cause runtime failures
_MYPY_HIGH_SEVERITY_CODES: set[str] = {
    "return-value",      # Incompatible return value - can cause unexpected behavior
    "arg-type",          # Argument type mismatch - can cause runtime errors
    "call-arg",          # Unexpected/missing argument - runtime TypeError
    "index",             # Invalid index type - runtime TypeError/KeyError
    "attr-defined",      # Attribute not defined - runtime AttributeError
    "union-attr",        # Attribute access on union with None - potential AttributeError
    "operator",          # Unsupported operand types - runtime TypeError
    "override",          # Incompatible override - can break polymorphism
    "assignment",        # Incompatible assignment - can cause downstream errors
}


def severity_for_mypy(mypy_severity: str, error_code: str | None) -> Severity:
    """
    Map MyPy severity and error codes to Severity enum.

    Severity mapping:
      - severity="note" -> LOW (informational messages)
      - severity="error" with high-severity code -> HIGH
      - severity="error" (default) -> MEDIUM

    High-severity codes are those more likely to cause runtime errors:
      - arg-type, return-value, call-arg, index, attr-defined, etc.

    Args:
        mypy_severity: MyPy severity field ("error" or "note")
        error_code: MyPy error code (e.g., "arg-type", "var-annotated")

    Returns:
        Severity enum value
    """
    # Notes are informational, low priority
    if mypy_severity == "note":
        return Severity.LOW

    # Check for high-severity error codes
    if error_code and error_code in _MYPY_HIGH_SEVERITY_CODES:
        return Severity.HIGH

    # Default for errors is MEDIUM
    return Severity.MEDIUM


# -------------------------------------------------------------------------
# Pydocstyle - Documentation Quality
# -------------------------------------------------------------------------

def severity_for_pydocstyle(code: str) -> Severity:
    """
    Map pydocstyle error codes to severity levels.

    Currently only handles missing docstring errors (D101-D103):
    - D101: Missing docstring in public class
    - D102: Missing docstring in public method
    - D103: Missing docstring in public function

    All missing docstring issues are LOW severity as they:
    - Don't affect runtime behavior
    - Are quality/maintainability improvements
    - Should be fixed but aren't critical bugs

    Other pydocstyle codes (D200, D212, D400, etc.) are not supported
    and will be filtered out by the parser.

    Args:
        code: Pydocstyle error code (should be D101, D102, or D103)

    Returns:
        Severity.LOW for D101-D103 codes
    """
    # Only D101, D102, D103 are expected (parser filters others)
    # All missing docstrings are LOW severity
    if code in ["D101", "D102", "D103"]:
        return Severity.LOW

    # Defensive: if other codes slip through, still return LOW
    # but this shouldn't happen with parser filtering
    return Severity.LOW

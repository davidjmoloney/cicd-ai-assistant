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
    # F-series: Pyflakes — logical errors
    "F401": Severity.LOW,    # unused import - low risk, trivial fix
    "F541": Severity.LOW,    # extraneous f-string prefix - low risk, cosmetic
    "F601": Severity.HIGH,   # dictionary key repeated - duplicate keys cause data loss
    "F811": Severity.MEDIUM, # redefinition of unused name - can mask bugs
    "F821": Severity.HIGH,   # undefined name - runtime NameError
    "F823": Severity.HIGH,   # local variable referenced before assignment - runtime UnboundLocalError
    "F841": Severity.MEDIUM, # unused variable - semantics can be tricky; ruff marks fix unsafe often

    # E-series: pycodestyle — style violations
    "E402": Severity.MEDIUM, # module level import not at top of file - can cause import order bugs
    "E701": Severity.LOW,    # multiple statements on one line (colon) - style issue
    "E702": Severity.LOW,    # multiple statements on one line (semicolon) - style issue
    "E713": Severity.LOW,    # test for membership should be 'not in' - style preference
    "E722": Severity.MEDIUM, # bare except - catches system exits and keyboard interrupts
    "E731": Severity.LOW,    # do not assign lambda, use def - readability preference

    # B-series: flake8-bugbear — common bug patterns
    "B002": Severity.HIGH,   # unary prefix increment - Python doesn't support ++x, silently wrong
    "B006": Severity.HIGH,   # mutable default argument - shared state across calls
    "B007": Severity.LOW,    # unused loop variable - should use _ prefix
    "B008": Severity.MEDIUM, # function call in default argument - evaluated once at definition time
    "B009": Severity.LOW,    # getattr with constant - should use dot access
    "B010": Severity.LOW,    # setattr with constant - should use dot access
    "B011": Severity.MEDIUM, # assert False - use raise AssertionError instead
    "B015": Severity.MEDIUM, # pointless comparison - result not used, likely a bug
    "B017": Severity.HIGH,   # assertRaises(Exception) - too broad, hides real failures
    "B018": Severity.MEDIUM, # useless expression - statement has no effect
    "B020": Severity.HIGH,   # loop variable overrides iterator - always a bug
    "B023": Severity.HIGH,   # function uses loop variable - late binding closure bug
    "B024": Severity.MEDIUM, # abstract class without abstract methods
    "B025": Severity.MEDIUM, # duplicate except handler - dead code in exception handling
    "B026": Severity.MEDIUM, # star-arg unpacking after keyword arg - unexpected behavior
    "B028": Severity.MEDIUM, # warnings.warn without stacklevel
    "B029": Severity.MEDIUM, # except with empty tuple - catches nothing
    "B032": Severity.MEDIUM, # possible unintentional type annotation (no assignment)
    "B034": Severity.MEDIUM, # re.sub/split/subn without flags= keyword - positional flags error-prone
    "B039": Severity.HIGH,   # mutable ContextVar default - shared state like B006

    # UP-series: pyupgrade — modernize for py312
    "UP001": Severity.LOW,   # useless metaclass=type - py3 default
    "UP003": Severity.LOW,   # type() instead of __class__ - style modernization
    "UP004": Severity.LOW,   # useless object inheritance - py3 default
    "UP006": Severity.LOW,   # use builtin type instead of typing.List etc
    "UP007": Severity.LOW,   # use X | Y instead of Union[X, Y]
    "UP008": Severity.LOW,   # use super() instead of super(__class__, self)
    "UP009": Severity.LOW,   # unnecessary utf-8 encoding declaration
    "UP010": Severity.LOW,   # unnecessary __future__ import
    "UP012": Severity.LOW,   # unnecessary encode("utf-8")
    "UP015": Severity.LOW,   # redundant open mode "r"
    "UP018": Severity.LOW,   # unnecessary call to str()/bytes()/int()/float() literal constructor
    "UP031": Severity.LOW,   # use format specifiers instead of %-formatting
    "UP032": Severity.LOW,   # use f-string instead of .format()
    "UP034": Severity.LOW,   # extraneous parentheses
    "UP035": Severity.LOW,   # deprecated typing import - use collections.abc etc
    "UP036": Severity.LOW,   # version block outdated for target version
    "UP037": Severity.LOW,   # remove quotes from type annotation (PEP 604)
    "UP038": Severity.LOW,   # use X | Y in isinstance() instead of tuple
    "UP040": Severity.LOW,   # use TypeAlias for type aliases

    # I-series: isort — import ordering
    "I001": Severity.LOW,    # import block unsorted - auto-fixable, no runtime impact
    "I002": Severity.LOW,    # missing required import - auto-fixable

    # S-series: flake8-bandit — security
    "S101": Severity.LOW,    # use of assert - stripped in optimized bytecode, but common in non-prod
    "S102": Severity.HIGH,   # use of exec() - arbitrary code execution
    "S103": Severity.MEDIUM, # permissive file permissions (chmod)
    "S104": Severity.MEDIUM, # binding to all interfaces (0.0.0.0)
    "S105": Severity.HIGH,   # hardcoded password in string
    "S106": Severity.HIGH,   # hardcoded password in function argument
    "S107": Severity.HIGH,   # hardcoded password in default value
    "S108": Severity.MEDIUM, # insecure temp file/dir usage
    "S110": Severity.MEDIUM, # try-except-pass - silently swallowing exceptions
    "S112": Severity.MEDIUM, # try-except-continue - silently swallowing in loop
    "S113": Severity.MEDIUM, # requests call without timeout
    "S301": Severity.HIGH,   # use of pickle - deserialization of untrusted data
    "S303": Severity.HIGH,   # insecure hash function (MD5/SHA1 for security)
    "S307": Severity.HIGH,   # use of eval() - arbitrary code execution
    "S311": Severity.MEDIUM, # pseudo-random generator not suitable for security
    "S324": Severity.HIGH,   # insecure hash function (hashlib)
    "S501": Severity.HIGH,   # requests with verify=False - disables TLS verification
    "S506": Severity.MEDIUM, # unsafe yaml load
    "S602": Severity.HIGH,   # subprocess with shell=True
    "S603": Severity.MEDIUM, # subprocess without shell - still review arguments
    "S605": Severity.HIGH,   # starting process with a shell
    "S607": Severity.MEDIUM, # starting process with partial path
    "S608": Severity.HIGH,   # SQL injection via string formatting
    "S701": Severity.HIGH,   # jinja2 autoescape disabled - XSS risk
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

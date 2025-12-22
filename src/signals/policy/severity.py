# signals/policy/severity.py
from __future__ import annotations

from signals.models import Severity, SignalType

# v1: conservative, explicit, deterministic.
# You can improve later by using a config file (yaml/toml) with rule->severity.

# Ruff specifics:
# - Ruff rule prefixes don't perfectly equal severity, so don't pretend they do.
# - Start with a small mapping of *known safe autofix* rules to LOW/MEDIUM.
# - Everything else defaults to MEDIUM so it shows up but doesn't outrank security/tests.

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
    return _RUFF_CODE_TO_SEVERITY.get(code, Severity.MEDIUM)


# -------------------------------------------------------------------------
# PSEUDOCODE PLACEHOLDERS
# -------------------------------------------------------------------------

def severity_for_bandit(issue_severity: str, issue_confidence: str) -> Severity:
    """
    PSEUDOCODE:
      map = {"HIGH": CRITICAL, "MEDIUM": HIGH/MEDIUM, "LOW": LOW}
      if confidence is HIGH and severity is LOW, maybe bump to MEDIUM
      return result
    """
    raise NotImplementedError


def severity_for_mypy(mypy_severity: str, error_code: str | None) -> Severity:
    """
    PSEUDOCODE:
      if mypy_severity == "error": return MEDIUM (or HIGH for certain codes)
      if mypy_severity == "note": return LOW
    """
    raise NotImplementedError

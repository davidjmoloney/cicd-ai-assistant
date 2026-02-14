# Breakdown of CICD Signalling configs per tool type

## Ruff Format
### Overview of Signals
Ruff format checks enforce consistent code style (whitespace, line breaks, quote style, trailing commas).
Each violation produces a unified diff hunk with the exact edit needed.
All format signals are **LOW** severity with **SAFE** applicability — they are auto-applied without LLM involvement.

Output format: unified diff (`--diff` flag). Parser: `parse_ruff_format_diff()`.

### Run Command
```bash
ruff format --diff   --target-version py312  \
 --line-length 150 --exclude 'tests,migrations' \
  prospecting/ authentication/ watchlist/ ria/ \
  meeting_prep/ google_integration/ \
  hubspot/ outlook/ salesforce/ \
 > rf-results.txt
``` 

## Ruff Lint
### Overview of Signals
Selected rule sets: **E, F, B, UP, I, S**

- **E** (pycodestyle errors) — PEP 8 style violations: indentation, whitespace, statement structure.
  Catches basic readability issues that can occasionally mask bugs (e.g., E722 bare `except`).
- **F** (pyflakes) — Logical errors: unused imports (F401), undefined names (F821), redefined variables (F811).
  These are real bugs or dead code, not just style.
- **B** (flake8-bugbear) — Common bug patterns: mutable default arguments, `assert` on tuples (always truthy),
  `except Exception` without re-raise, redundant `isinstance` calls. These catch defects that pass syntax checks.
- **UP** (pyupgrade) — Outdated Python patterns for the target version (3.12): legacy `typing.Optional` instead of
  `X | None`, old-style `super()`, obsolete string formatting. Keeps code modern and consistent.
- **I** (isort) — Import ordering and grouping. Ensures stdlib, third-party, and first-party imports are
  consistently separated. Auto-fixable.
- **S** (flake8-bandit) — Security issues: hardcoded passwords, `eval()`, `subprocess` with `shell=True`,
  insecure hash algorithms, use of `exec`. Surfaces risks that static analysis can catch early.

Ignored rules: **E203, E501**
- **E203** (whitespace before `:`) — Conflicts with ruff formatter style for slice notation like `x[1 : 2]`.
  The formatter owns whitespace decisions, so this would produce false positives.
- **E501** (line too long) — Redundant when `line-length=150` is enforced by `ruff format`.
  Keeping it would double-report what the format diff already captures.

Severity is mapped per rule code in `src/signals/policy/severity.py`. Known codes (F401, F821, E722, etc.)
have explicit mappings; all others default to **MEDIUM**.

Output format: JSON array (`--output-format=json`). Parser: `parse_ruff_lint_results()`.

### Run Command
```bash
ruff check --output-format=json \
  --target-version py312 \
  --line-length 150 \
  --select E,F,B,UP,I,S \
  --ignore E203,E501 \
  --exclude 'tests,migrations' \
  prospecting/ authentication/ watchlist/ ria/ \
  meeting_prep/ google_integration/ \
  hubspot/ outlook/ salesforce/ \
  > rl-results.json
```

## Mypy
### Overview of Signals
Mypy performs static type checking against Python 3.12 type semantics. Signals cover type mismatches
at call sites, return values, assignments, attribute access, and operator usage.

Key config choices:
- **`--follow-imports=normal`** — Resolves real types from imported modules instead of treating them as `Any`.
  This enables cross-module type checking (e.g., catching wrong argument types passed to functions defined
  in other modules). Most resulting errors are self-contained because mypy includes both expected and actual
  types directly in the error message.
- **`--no-implicit-optional`** — Flags `def foo(x: int = None)` as an error; requires explicit `int | None`.
  Catches a real category of type bugs where None can flow into code that doesn't expect it.
- **`--ignore-missing-imports`** — Suppresses noise from third-party libraries without type stubs.
  Removing this would flood signals with unactionable errors for untyped dependencies.

Severity is mapped in `src/signals/policy/severity.py`:
- **HIGH**: error codes likely to cause runtime failures — `arg-type`, `return-value`, `call-arg`, `index`,
  `attr-defined`, `union-attr`, `operator`, `override`, `assignment`
- **MEDIUM**: all other error codes
- **LOW**: mypy notes (informational)

Output format: newline-delimited JSON (`--output=json`). Parser: `parse_mypy_results()`.

### Run Command
```bash
mypy --output=json \
  --python-version 3.12 \
  --no-implicit-optional \
  --ignore-missing-imports \
  --follow-imports=normal \
  --exclude 'tests,migrations' \
  prospecting/ authentication/ watchlist/ ria/ \
  meeting_prep/ google_integration/ \
  hubspot/ outlook/ salesforce/ \
  > mp-results.json
```

### Notes
**On `--follow-imports=normal` and fixability with single-file context.**

Most cross-module errors are fixable without seeing the imported module source because mypy
includes both types in the error message:
- `arg-type`: "Argument 1 to "save" has incompatible type "str"; expected "int"" — fix at call site
- `return-value`: "Incompatible return value type (got "str", expected "User")" — fix the return
- `assignment`: "Incompatible types in assignment (expression has type "str", variable has type "int")"
- `union-attr`: "Item "None" of "Optional[User]" has no attribute "name"" — add a None guard
- `call-arg`: "Unexpected keyword argument "nme" for "User"" — typo is obvious from the message
- `override`: "Return type "str" incompatible with return type "int" in superclass "Base""

A minority of errors are harder without cross-file context:
- `attr-defined`: "User" has no attribute "full_name" — LLM can't see available attributes
- `arg-type` (complex): expected "UserConfig" — LLM can't see the type definition
- `call-overload`: no matching overload — LLM can't see overload signatures

These still surface real issues even if the LLM fix is imperfect.
Cross-file context support is stubbed in `context_builder.py` (`_extract_parent_class_method`,
`build_repo_context_index`) for future implementation.

## Pydocstyle
### Overview of Signals
Pydocstyle checks for missing docstrings on public API surfaces. Only three rule codes are used:
- **D101** — Missing docstring in public class
- **D102** — Missing docstring in public method
- **D103** — Missing docstring in public function

All are **LOW** severity. They don't affect runtime behavior but improve code maintainability
and enable better IDE/documentation tooling. The parser filters out all other pydocstyle codes.

Output format: plain text (two-line blocks per error). Parser: `parse_pydocstyle_results()`.

### Run Command
```bash
pydocstyle \
  --select=D101,D102,D103 \
  --match='(?!test_).*\.py' \
  --match-dir='(?!tests|migrations).*' \
  prospecting/ authentication/ watchlist/ ria/ \
  meeting_prep/ google_integration/ \
  hubspot/ outlook/ salesforce/ \
  > pds-results.txt
```

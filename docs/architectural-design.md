# Architectural Design Document

Comprehensive documentation of the CI/CD AI Assistant architecture, covering signal flow, data structures, fix generation, and PR creation.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Data Structures](#2-data-structures)
3. [Signal Parsing](#3-signal-parsing)
4. [Prioritization and Grouping](#4-prioritization-and-grouping)
5. [Deterministic vs LLM-Assisted Fixes](#5-deterministic-vs-llm-assisted-fixes)
6. [Context Gathering](#6-context-gathering)
7. [Signal-Specific Prompts and Windows](#7-signal-specific-prompts-and-windows)
8. [Code Edit Application](#8-code-edit-application)
9. [PR Generation](#9-pr-generation)

---

## 1. System Overview

The CI/CD AI Assistant ingests signals from static analysis tools (linters, type checkers, formatters, docstring checks), generates code fixes using either deterministic rules or LLM assistance, and creates pull requests with the fixes.

### Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ENTRY POINT                                    │
│                              src/main.py                                    │
│                                                                             │
│   CLI interface, artifact discovery, pipeline orchestration, run metrics   │
│   Config: CONFIDENCE_THRESHOLD, SIGNALS_PER_PR, LLM_PROVIDER, LOG_LEVEL    │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            CI/CD TOOL OUTPUTS                               │
│   ruff lint → JSON    mypy → JSON    pydocstyle → text    ruff format → diff│
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          1. SIGNAL PARSING                                  │
│                     src/signals/parsers/*.py                                │
│                                                                             │
│   Tool-specific parsers convert raw output → normalized FixSignal objects  │
│   Each signal includes: file, span, rule_code, message, severity, fix?     │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ list[FixSignal]
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         2. PRIORITIZATION                                   │
│                   src/orchestrator/prioritizer.py                           │
│                                                                             │
│   Groups signals by tool and batches for processing                         │
│   Priority: TYPE_CHECK > LINT > DOCSTRING > FORMAT              │
│   FORMAT signals grouped by file; others chunked by max_group_size=3       │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │ list[SignalGroup]
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          3. FIX PLANNING                                    │
│                   src/orchestrator/fix_planner.py                           │
│                                                                             │
│   Routes each group to appropriate fix path:                                │
│   ┌─────────────────────────────┐  ┌─────────────────────────────────────┐ │
│   │   DETERMINISTIC PATH        │  │     LLM-ASSISTED PATH               │ │
│   │   (FORMAT signals)          │  │     (LINT, TYPE_CHECK, etc.)        │ │
│   │                             │  │                                     │ │
│   │   Extract fix.edits from    │  │   1. Build context (snippets,      │ │
│   │   FixSignal directly        │  │      imports, functions)            │ │
│   │   No LLM call needed        │  │   2. Send to LLM with prompts       │ │
│   │   confidence = 1.0          │  │   3. Parse response to FixPlan      │ │
│   └──────────────┬──────────────┘  └─────────────────┬───────────────────┘ │
│                  │                                   │                      │
│                  └──────────────┬────────────────────┘                      │
└─────────────────────────────────┼───────────────────────────────────────────┘
                                  │ FixPlan
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         4. PR GENERATION                                    │
│                    src/github/pr_generator.py                               │
│                                                                             │
│   Applies edits to files via GitHub API and creates pull request           │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Module Responsibilities

| Module | Path | Responsibility |
|--------|------|----------------|
| **Main** | `src/main.py` | CLI entry point, artifact discovery, pipeline orchestration, run metrics |
| **Signals** | `src/signals/` | Data models, parsers, severity policy |
| **Orchestrator** | `src/orchestrator/` | Prioritization, context building, fix planning |
| **Agents** | `src/agents/` | LLM integration, prompts, response parsing |
| **GitHub** | `src/github/` | PR creation, edit application |

---

## 2. Data Structures

### 2.1 FixSignal — The Core Unit

Every signal from every tool is normalized into a `FixSignal`. This is the universal interface between parsing and fix generation.

```python
@dataclass(frozen=True)
class FixSignal:
    signal_type: SignalType      # LINT | FORMAT | TYPE_CHECK | DOCSTRING
    severity: Severity           # CRITICAL | HIGH | MEDIUM | LOW
    file_path: str               # Normalized path relative to repo root
    span: Optional[Span]         # Location in file (start/end positions)
    rule_code: Optional[str]     # Tool-specific code (e.g., "F401", "arg-type")
    message: str                 # Human-readable error description
    docs_url: Optional[str]      # Link to rule documentation
    fix: Optional[Fix]           # Deterministic fix if available
```

**Key design decisions:**

1. **Frozen dataclass** — Signals are immutable to prevent accidental modification during pipeline processing.

2. **Optional `fix` field** — Present when the tool provides deterministic edits (ruff lint with safe fixes, ruff format). Absent when human/LLM judgment is needed (mypy, pydocstyle).

3. **Tool-agnostic** — The same structure works for all tools. Tool-specific data is normalized into common fields.

### 2.2 Supporting Types

```python
class SignalType(str, Enum):
    LINT = "lint"           # Code quality issues (ruff)
    FORMAT = "format"       # Formatting issues (ruff format)
    TYPE_CHECK = "type_check"  # Type errors (mypy)
    DOCSTRING = "docstring" # Missing documentation (pydocstyle)

class Severity(str, Enum):
    CRITICAL = "critical"   # Must fix immediately
    HIGH = "high"           # Likely causes runtime errors
    MEDIUM = "medium"       # Should fix, potential issues
    LOW = "low"             # Nice to fix, cosmetic/style

class FixApplicability(str, Enum):
    SAFE = "safe"           # Can apply automatically without review
    UNSAFE = "unsafe"       # May change behavior, needs review
    UNKNOWN = "unknown"     # Applicability not determined

@dataclass(frozen=True)
class Position:
    row: int                # 1-based line number
    column: int             # 0-based column offset

@dataclass(frozen=True)
class Span:
    start: Position
    end: Position

@dataclass(frozen=True)
class TextEdit:
    span: Span              # Region to replace
    content: str            # Replacement text

@dataclass(frozen=True)
class Fix:
    applicability: FixApplicability
    message: Optional[str]  # Fix description
    edits: Sequence[TextEdit]
```

### 2.3 SignalGroup — Batching for Processing

Signals are grouped for efficient batch processing:

```python
@dataclass(frozen=True)
class SignalGroup:
    tool_id: str            # "ruff", "mypy", "pydocstyle", "ruff-format"
    signal_type: SignalType
    signals: list[FixSignal]
```

Groups are **tool-homogeneous** — all signals in a group come from the same tool. This allows:
- Tool-specific prompts
- Consistent context requirements
- Optimized batch sizes per tool

### 2.4 FixPlan — The Fix Output

The output of fix generation, ready for PR creation:

```python
@dataclass
class FixPlan:
    group_tool_id: str
    group_signal_type: str
    file_edits: list[FileEdit]
    summary: str
    warnings: list[str]
    confidence: float       # 0.0-1.0

@dataclass
class FileEdit:
    file_path: str
    edits: list[CodeEdit]
    reasoning: str

@dataclass
class CodeEdit:
    edit_type: EditType     # REPLACE | INSERT | DELETE
    span: Span
    content: str
    description: str
```

---

## 3. Signal Parsing

Each CI/CD tool has a dedicated parser that converts raw output to `FixSignal` objects.

### 3.1 Parser Interface

All parsers follow the same pattern:

```python
def parse_{tool}_results(
    raw: str,
    *,
    repo_root: str | None = None,
) -> list[FixSignal]:
    """Parse raw tool output to normalized FixSignals."""
```

### 3.2 Implemented Parsers

| Parser | File | Input Format | Output |
|--------|------|--------------|--------|
| **Ruff Lint** | `parsers/ruff.py` | JSON array | `SignalType.LINT` with optional `Fix` |
| **Ruff Format** | `parsers/ruff.py` | Unified diff | `SignalType.FORMAT` with `Fix` |
| **Mypy** | `parsers/mypy.py` | Newline-delimited JSON | `SignalType.TYPE_CHECK`, no fix |
| **Pydocstyle** | `parsers/pydocstyle.py` | Text (custom format) | `SignalType.DOCSTRING`, no fix |

### 3.3 Ruff Lint Parser

Ruff provides the richest signal format with optional deterministic fixes:

```python
# Input: ruff check --output-format=json
{
    "code": "F401",
    "message": "'os' imported but unused",
    "filename": "src/main.py",
    "location": {"row": 1, "column": 1},
    "end_location": {"row": 1, "column": 10},
    "fix": {
        "applicability": "safe",
        "message": "Remove unused import",
        "edits": [
            {"content": "", "location": {...}, "end_location": {...}}
        ]
    },
    "url": "https://docs.astral.sh/ruff/rules/F401"
}
```

The parser:
1. Extracts `rule_code` from `code`
2. Maps severity via `severity_for_ruff(code)`
3. Normalizes file path via `to_repo_relative()`
4. Converts location objects to `Span`
5. Converts fix edits to `Fix` with `TextEdit` objects

### 3.4 Mypy Parser

Mypy provides diagnostics without fixes:

```python
# Input: mypy --output=json (newline-delimited)
{"file": "app/config.py", "line": 55, "column": 33,
 "message": "Argument has incompatible type",
 "code": "arg-type", "severity": "error"}
```

The parser:
1. Extracts error code and message
2. Maps severity via `severity_for_mypy(severity, code)`
3. Creates single-position `Span` (mypy doesn't provide end position)
4. Sets `fix=None` — mypy fixes always require LLM

### 3.5 Pydocstyle Parser

Pydocstyle uses a custom text format:

```
app/main.py:303 in public class `CORSDebugMiddleware`:
        D101: Missing docstring in public class
```

The parser:
1. Regex matches the location line and error line
2. Filters to only D101, D102, D103 (missing docstrings)
3. Extracts target type (class/method/function) from location
4. Sets `fix=None` — docstrings require LLM generation

### 3.6 Severity Mapping

Each tool has a severity policy function:

```python
# signals/policy/severity.py

def severity_for_ruff(code: str) -> Severity:
    """Map ruff rule codes to severity."""
    _RUFF_CODE_TO_SEVERITY = {
        "F401": Severity.LOW,    # Unused import
        "F821": Severity.HIGH,   # Undefined name (NameError)
        "F601": Severity.HIGH,   # Duplicate dict key
        "E722": Severity.MEDIUM, # Bare except
        # ... more mappings
    }
    return _RUFF_CODE_TO_SEVERITY.get(code, Severity.MEDIUM)

def severity_for_mypy(mypy_severity: str, error_code: str | None) -> Severity:
    """Map mypy severity and codes."""
    _HIGH_SEVERITY_CODES = {"arg-type", "return-value", "attr-defined", ...}

    if mypy_severity == "note":
        return Severity.LOW
    if error_code in _HIGH_SEVERITY_CODES:
        return Severity.HIGH
    return Severity.MEDIUM
```

---

## 4. Prioritization and Grouping

The `Prioritizer` class converts a flat list of signals into ordered, batched groups.

### 4.1 Priority Ordering

Signal types are processed in priority order:

```python
SIGNAL_TYPE_PRIORITY = {
    SignalType.TYPE_CHECK: 1,   # Type errors can cause runtime failures
    SignalType.LINT: 2,         # Code quality
    SignalType.DOCSTRING: 3,    # Documentation quality
    SignalType.FORMAT: 4,       # Lowest - cosmetic changes
}
```

**Rationale:** type errors can cause runtime failures. Format changes are purely cosmetic and safe to defer.

### 4.2 Tool Resolution

Signals are grouped by their source tool:

```python
def default_tool_resolver(sig: FixSignal) -> str:
    if sig.signal_type == SignalType.FORMAT:
        return "ruff-format"
    if sig.signal_type == SignalType.TYPE_CHECK:
        return "mypy"
    if sig.signal_type == SignalType.DOCSTRING:
        return "pydocstyle"
    if sig.docs_url and "docs.astral.sh/ruff" in sig.docs_url:
        return "ruff"
    return "unknown"
```

### 4.3 Grouping Strategies

**Non-FORMAT signals:** Chunked into groups of `max_group_size=3` per tool.

```
Input:  [ruff_sig_1, ruff_sig_2, ruff_sig_3, ruff_sig_4, mypy_sig_1]
Output: [
    SignalGroup(tool="ruff", signals=[sig_1, sig_2, sig_3]),
    SignalGroup(tool="ruff", signals=[sig_4]),
    SignalGroup(tool="mypy", signals=[sig_1]),
]
```

**FORMAT signals:** Grouped by file (not by max_group_size).

```
Input:  [format_main_1, format_main_2, format_utils_1]
Output: [
    SignalGroup(tool="ruff-format", signals=[main_1, main_2]),  # Same file
    SignalGroup(tool="ruff-format", signals=[utils_1]),
]
```

**Rationale for file-based FORMAT grouping:**
1. Format changes within a file are interdependent (line numbers shift)
2. Applying all format changes atomically avoids drift
3. Format is idempotent and safe, so larger groups have no risk
4. Enables bypassing LLM entirely for format fixes

### 4.4 Prioritize Method

```python
def prioritize(self, signals: list[FixSignal]) -> list[SignalGroup]:
    # 1. Separate FORMAT from others
    format_signals, other_signals = partition(signals, is_format)

    # 2. Process non-FORMAT with tool-based chunking
    other_groups = self._group_by_tool_chunked(other_signals)

    # 3. Process FORMAT with file-based grouping
    format_groups = self._group_format_by_file(format_signals)

    # 4. Combine and sort by priority
    all_groups = other_groups + format_groups
    all_groups.sort(key=lambda g: SIGNAL_TYPE_PRIORITY[g.signal_type])

    return all_groups
```

---

## 5. Deterministic vs LLM-Assisted Fixes

The `FixPlanner` routes signal groups to the appropriate fix path.

### 5.1 Routing Logic

```python
def create_fix_plan(self, group: SignalGroup) -> PlannerResult:
    # FORMAT signals with AUTO_APPLY=true → deterministic path
    if group.signal_type == SignalType.FORMAT and self._auto_apply_format:
        return self._create_direct_fix_plan(group)

    # Everything else → LLM path
    return self._create_llm_fix_plan(group)
```

### 5.2 Deterministic Path (No LLM)

Used when:
- Signal type is `FORMAT`
- `AUTO_APPLY_FORMAT_FIXES=true` (default)

The fix is extracted directly from `FixSignal.fix.edits`:

```python
def _create_direct_fix_plan(self, group: SignalGroup) -> PlannerResult:
    file_edits = {}

    for signal in group.signals:
        if signal.fix is None:
            continue

        for text_edit in signal.fix.edits:
            # Convert TextEdit → CodeEdit
            code_edit = CodeEdit(
                edit_type=EditType.REPLACE,
                span=text_edit.span,
                content=text_edit.content,
                description="Apply formatting",
            )
            file_edits[signal.file_path].edits.append(code_edit)

    return PlannerResult(
        success=True,
        fix_plan=FixPlan(file_edits=list(file_edits.values())),
        used_llm=False,
    )
```

**Benefits:**
- **Fast:** No network calls, pure Python conversion
- **Free:** No LLM API costs
- **Deterministic:** Same input → same output
- **Safe:** Format changes don't alter semantics

### 5.3 LLM-Assisted Path

Used for:
- `LINT`, `TYPE_CHECK`, `DOCSTRING` signals
- FORMAT signals when `AUTO_APPLY_FORMAT_FIXES=false`

The process:

```python
def _create_llm_fix_plan(self, group: SignalGroup) -> PlannerResult:
    # 1. Build context around each signal
    context = self._context_builder.build_group_context(group)

    # 2. Generate fix via LLM
    agent_result = self._agent_handler.generate_fix_plan(context)

    # 3. Return result
    return PlannerResult(
        fix_plan=agent_result.fix_plan,
        used_llm=True,
    )
```

---

## 6. Context Gathering

The `ContextBuilder` extracts relevant code context for each signal to provide the LLM with sufficient information to generate fixes.

### 6.1 Context Components

For each signal, the context includes:

| Component | Description | When Included |
|-----------|-------------|---------------|
| **edit_snippet** | Small code region LLM should modify | Always |
| **code_context.window** | Larger surrounding context for understanding | Always |
| **code_context.imports** | Import statements from file top | Based on rule |
| **code_context.enclosing_function** | Full function containing the signal | Based on rule |
| **code_context.try_except** | Enclosing try/except block | For E722 |
| **code_context.class_definition** | Class header and methods | For D101, attr errors |
| **code_context.type_aliases** | Type definitions (TypeVar, etc.) | For complex type errors |

### 6.2 Edit Snippet vs Context Window

**Edit Snippet** — The focused region the LLM should modify and return:
- Smaller, targeted
- Includes `error_line_in_snippet` to locate the issue
- LLM returns only this portion, fixed

**Context Window** — Broader surrounding code for understanding:
- Larger (±10-20 lines around signal)
- Read-only reference
- LLM should NOT return this

This separation:
1. Reduces token usage (LLM only returns small snippet)
2. Prevents LLM from "improving" unrelated code
3. Keeps fixes focused and reviewable

### 6.3 Context Building Process

```python
def build_group_context(self, group: SignalGroup) -> dict:
    result = {
        "group": {
            "tool_id": group.tool_id,
            "signal_type": group.signal_type.value,
            "group_size": len(group.signals),
        },
        "signals": []
    }

    for signal in group.signals:
        # 1. Read source file
        text, lines, error = self._read_file(signal.file_path)

        # 2. Get window spec based on rule code
        window_spec = get_edit_window_spec(signal)

        # 3. Get context requirements based on rule
        requirements = get_context_requirements(signal)

        # 4. Build edit snippet (small, for LLM to fix)
        edit_snippet = self._build_edit_snippet(signal, lines, window_spec)

        # 5. Build context window (large, for understanding)
        context_window = self._build_context_window(signal, lines)

        # 6. Add conditional context based on requirements
        code_context = {"window": context_window}

        if requirements.include_imports:
            code_context["imports"] = self._extract_import_block(lines)

        if requirements.include_enclosing_function:
            code_context["enclosing_function"] = self._extract_enclosing_function(
                lines, signal.span
            )

        if requirements.include_try_except:
            code_context["try_except"] = self._extract_try_except_block(
                lines, signal.span
            )

        # 7. Add to result
        result["signals"].append({
            "signal": self._signal_metadata(signal),
            "edit_snippet": edit_snippet,
            "code_context": code_context,
        })

    return result
```

### 6.4 Enclosing Function Extraction

Uses indentation-based heuristics:

```python
def _extract_enclosing_function(self, lines, span):
    """Find the function containing the signal's span."""
    target_row = span.start.row - 1  # 0-indexed

    # Walk upward to find 'def' or 'async def'
    func_start = None
    for i in range(target_row, -1, -1):
        line = lines[i]
        stripped = line.lstrip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            func_start = i
            break

    if func_start is None:
        return None

    # Determine function's indentation
    base_indent = len(lines[func_start]) - len(lines[func_start].lstrip())

    # Walk downward to find function end (next line with <= indent that isn't blank)
    func_end = func_start
    for i in range(func_start + 1, len(lines)):
        line = lines[i]
        if line.strip():  # Non-blank
            current_indent = len(line) - len(line.lstrip())
            if current_indent <= base_indent:
                break
            func_end = i

    return {
        "start_row": func_start + 1,
        "end_row": func_end + 1,
        "text": "".join(lines[func_start:func_end + 1]),
    }
```

---

## 7. Signal-Specific Prompts and Windows

Different signals need different context and prompts. This is controlled by two systems.

### 7.1 Edit Window Specification

`get_edit_window_spec(signal)` returns an `EditWindowSpec` that determines what code region to extract:

```python
@dataclass(frozen=True)
class EditWindowSpec:
    window_type: Literal["lines", "function", "imports", "try_except"]
    lines: int = 0        # For window_type='lines'
    min_context_lines: int = 10
    min_edit_lines: int = 2
```

**Window Types:**

| Type | Description | Used For |
|------|-------------|----------|
| `lines` | ±N lines around signal | Most errors |
| `function` | Full enclosing function | `F823`, `return-value` |
| `imports` | Import block only | `F401`, `I001`, `E402` |
| `try_except` | Enclosing try/except | `E722` (bare except) |

**Rule Code Mappings:**

```python
# Import-related → just imports
if rule_code in ["F401", "I001", "E402"]:
    return EditWindowSpec(window_type="imports")

# Try/except → just the try block
if rule_code == "E722":
    return EditWindowSpec(window_type="try_except")

# Trivial single-line (±1 line)
if rule_code in ["F541", "E711", "E712"]:
    return EditWindowSpec(window_type="lines", lines=1)

# Small context (±3 lines)
if rule_code in ["F601", "F841", "E731"]:
    return EditWindowSpec(window_type="lines", lines=3)

# Function-level type issues
if rule_code in ["union-attr", "return-value"]:
    return EditWindowSpec(window_type="function")

# Call-site type errors (±7 lines)
if rule_code in ["arg-type", "call-arg"]:
    return EditWindowSpec(window_type="lines", lines=7)

# Default: ±7 lines
return EditWindowSpec(window_type="lines", lines=7)
```

### 7.2 Context Requirements

`get_context_requirements(signal)` returns a `ContextRequirements` that controls what additional context to gather:

```python
@dataclass(frozen=True)
class ContextRequirements:
    # Base context
    include_imports: bool = True
    include_enclosing_function: bool = True
    include_try_except: bool = False

    # Additional specialized context
    needs_class_definition: bool = False
    needs_type_aliases: bool = False
    needs_related_functions: bool = False
    needs_module_constants: bool = False
```

**Examples:**

```python
# Import errors - only need imports
if rule_code in ["F401", "I001", "E402"]:
    return ContextRequirements(
        include_imports=True,
        include_enclosing_function=False,
    )

# Bare except - only need try/except block
if rule_code == "E722":
    return ContextRequirements(
        include_imports=False,
        include_enclosing_function=False,
        include_try_except=True,
    )

# Docstring for class - need full class definition
if rule_code == "D101":
    return ContextRequirements(
        include_enclosing_function=False,
        needs_class_definition=True,
    )

# Type error mentioning self. - need class context
if rule_code == "attr-defined" and "self." in message:
    return ContextRequirements(
        include_enclosing_function=True,
        needs_class_definition=True,
    )
```

### 7.3 Tool-Specific Prompts

The `get_system_prompt(tool_id)` function returns a base prompt plus tool-specific guidance:

```python
def get_system_prompt(tool_id: str | None) -> str:
    prompt = BASE_SYSTEM_PROMPT

    if tool_id in TOOL_SPECIFIC_PROMPTS:
        prompt += "\n\n" + TOOL_SPECIFIC_PROMPTS[tool_id]

    return prompt
```

**Prompt Components:**

1. **BASE_SYSTEM_PROMPT** — Core instructions for all tools:
   - Response format (delimited blocks)
   - Edit snippet semantics
   - Row/column conventions

2. **MYPY_TYPE_CHECK_GUIDANCE** — Critical for type errors:
   - ⚠️ Never bypass validation with `or ""`
   - Prefer type annotations over defaults
   - Use type guards and assertions after validation
   - Preserve security checks (JWT, credentials)

3. **RUFF_LINT_GUIDANCE** — For lint fixes:
   - Safe patterns for removing unused code
   - Modernization suggestions (Union → `|`)
   - Complexity warning handling

4. **PYDOCSTYLE_DOCSTRING_GUIDANCE** — For docstring generation:
   - Google-style format
   - Args, Returns, Raises sections
   - Match existing codebase style


### 7.4 LLM Response Format

The LLM returns fixes in a delimited format:

```
===== FIX FOR: src/main.py =====
CONFIDENCE: 0.9
REASONING: Added type annotation to resolve arg-type error
```FIXED_CODE
def process(data: str) -> None:
    ...
```
WARNINGS: None
===== END FIX =====
```

This format is:
1. Easy to parse with regex
2. Clearly separates multiple fixes
3. Includes metadata (confidence, reasoning, warnings)
4. Returns only the edit snippet (not full file)

---

## 8. Code Edit Application

The `apply_edits_to_content()` function applies `CodeEdit` objects to file content.

### 8.1 Edit Types

```python
class EditType(str, Enum):
    REPLACE = "replace"   # Replace span with content
    INSERT = "insert"     # Insert content at position (start==end)
    DELETE = "delete"     # Delete span (content is empty)
```

### 8.2 Application Order

Edits must be applied **bottom-to-top** to preserve line numbers:

```python
def apply_edits_to_content(content: str, edits: list[CodeEdit]) -> str:
    lines = content.splitlines(keepends=True)

    # Sort by position descending (bottom-to-top)
    sorted_edits = sorted(
        edits,
        key=lambda e: (e.span.start.row, e.span.start.column),
        reverse=True,
    )

    for edit in sorted_edits:
        lines = _apply_edit(lines, edit)

    return "".join(lines)
```

### 8.3 Single Edit Application

```python
def _apply_edit(lines: list[str], edit: CodeEdit) -> list[str]:
    # Convert 1-based to 0-based
    start_row = edit.span.start.row - 1
    end_row = edit.span.end.row - 1
    start_col = edit.span.start.column
    end_col = edit.span.end.column

    if edit.edit_type == EditType.DELETE:
        # Remove text in span
        prefix = lines[start_row][:start_col]
        suffix = lines[end_row][end_col:]
        lines[start_row:end_row + 1] = [prefix + suffix]

    elif edit.edit_type == EditType.INSERT:
        # Insert at position (start == end)
        line = lines[start_row]
        lines[start_row] = line[:start_col] + edit.content + line[start_col:]

    elif edit.edit_type == EditType.REPLACE:
        # Replace span with content
        prefix = lines[start_row][:start_col]
        suffix = lines[end_row][end_col:]
        new_content = prefix + edit.content + suffix
        lines[start_row:end_row + 1] = new_content.splitlines(keepends=True)

    return lines
```

### 8.4 Multi-Line Handling

The replacement logic handles multi-line edits:

```
Before:
    Line 1: "def foo():⏎"
    Line 2: "    pass⏎"

Edit: REPLACE span (1,0)-(2,8) with "def foo():\n    return 42\n"

After:
    Line 1: "def foo():⏎"
    Line 2: "    return 42⏎"
```

---

## 9. PR Generation

The `PRGenerator` creates GitHub pull requests from `FixPlan` objects. This section is brief as the core logic is straightforward GitHub API usage.

### 9.1 Process Overview

```python
def create_pr(self, fix_plan: FixPlan, base_branch: str = None) -> PRResult:
    # 1. Get base branch SHA
    base_sha = self._get_ref_sha(base_branch or self._default_branch)

    # 2. Create feature branch
    branch_name = self._generate_branch_name(fix_plan)
    self._create_branch(branch_name, base_sha)

    # 3. Apply edits and commit each file
    for file_edit in fix_plan.file_edits:
        # Fetch current content
        content = self._get_file_content(file_edit.file_path, branch_name)

        # Apply edits
        new_content = apply_edits_to_content(content, file_edit.edits)

        # Commit to branch
        self._update_file(file_edit.file_path, new_content, branch_name, message)

    # 4. Create pull request
    pr = self._create_pull_request(branch_name, base_branch, title, body)

    # 5. Add labels
    self._add_labels(pr.number, ["ai-generated"])

    return PRResult(success=True, pr_url=pr.url, pr_number=pr.number)
```

### 9.2 Configuration

Environment variables:
- `GITHUB_TOKEN` — PAT with repo permissions
- `TARGET_REPO_OWNER` / `TARGET_REPO_NAME` — Target repository
- `TARGET_REPO_DEFAULT_BRANCH` — Base branch for PRs (default "main")
- `PR_BRANCH_PREFIX` — Branch prefix (default "cicd-agent-fix")
- `PR_LABELS` — Comma-separated labels (default "ai-generated")
- `PR_DRAFT_MODE` — Create as draft (default false)

### 9.3 Error Handling

- Retry logic with exponential backoff (4 retries, 2/4/8/16 seconds)
- Respects `Retry-After` header for rate limiting
- Returns `PRResult` with `success=False` and `error` message on failure

### 9.4 Branch Naming

```python
def _generate_branch_name(self, fix_plan: FixPlan) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    hash_suffix = hashlib.md5(fix_plan.summary.encode()).hexdigest()[:6]
    return f"{PREFIX}/{fix_plan.group_signal_type}/{timestamp}-{hash_suffix}"
    # e.g., "cicd-agent-fix/type_check/20260127-143022-a1b2c3"
```

---

## 10. Key Python Modules

### 10.1 Signals Package (`src/signals/`)

The data model and parsing layer.

| Module | Path | Description |
|--------|------|-------------|
| **models.py** | `src/signals/models.py` | Core data structures: `FixSignal`, `SignalType`, `Severity`, `Span`, `Position`, `TextEdit`, `Fix`, `FixApplicability`. All are frozen dataclasses for immutability. |
| **parsers/ruff.py** | `src/signals/parsers/ruff.py` | Parsers for ruff lint (JSON) and ruff format (unified diff). Exports `parse_ruff_lint_results()` and `parse_ruff_format_diff()`. |
| **parsers/mypy.py** | `src/signals/parsers/mypy.py` | Parser for mypy JSON output. Exports `parse_mypy_results()`. Handles newline-delimited JSON format. |
| **parsers/pydocstyle.py** | `src/signals/parsers/pydocstyle.py` | Parser for pydocstyle text output. Exports `parse_pydocstyle_results()`. Filters to D101-D103 codes only. |
| **policy/severity.py** | `src/signals/policy/severity.py` | Severity mapping functions: `severity_for_ruff()`, `severity_for_mypy()`, `severity_for_pydocstyle()`. Maps tool-specific codes to `Severity` enum. |
| **policy/path.py** | `src/signals/policy/path.py` | Path normalization: `to_repo_relative()`. Converts absolute paths to repo-relative paths. |

### 10.2 Orchestrator Package (`src/orchestrator/`)

Coordination, context building, and fix planning.

| Module | Path | Description |
|--------|------|-------------|
| **prioritizer.py** | `src/orchestrator/prioritizer.py` | Signal grouping and prioritization. Defines `SignalGroup` dataclass and `Prioritizer` class. Handles tool-based chunking and file-based FORMAT grouping. |
| **context_builder.py** | `src/orchestrator/context_builder.py` | Extracts code context for LLM prompts. `ContextBuilder` class with `build_group_context()` method. Handles edit snippets, context windows, imports, enclosing functions, try/except blocks. |
| **signal_requirements.py** | `src/orchestrator/signal_requirements.py` | Signal-specific configuration. Defines `EditWindowSpec` and `ContextRequirements` dataclasses. `get_edit_window_spec()` and `get_context_requirements()` map rule codes to appropriate window types and context needs. |
| **fix_planner.py** | `src/orchestrator/fix_planner.py` | Routes signals to fix paths. `FixPlanner` class with `create_fix_plan()`. Handles deterministic path (FORMAT) and LLM-assisted path. Defines `PlannerResult` dataclass. |

### 10.3 Agents Package (`src/agents/`)

LLM integration and prompt management.

| Module | Path | Description |
|--------|------|-------------|
| **agent_handler.py** | `src/agents/agent_handler.py` | LLM-based fix generation. Defines `FixPlan`, `FileEdit`, `CodeEdit`, `EditType`, `Span`, `Position` dataclasses. `AgentHandler` class with `generate_fix_plan()`. Handles prompt building and response parsing. |
| **llm_provider.py** | `src/agents/llm_provider.py` | LLM provider abstraction. Defines `LLMProvider` abstract base class, `LLMResponse`, `LLMError`. Implements `OpenAIProvider` and `ClaudeProvider`. Includes retry logic and `get_provider()` factory. |
| **tool_prompts.py** | `src/agents/tool_prompts.py` | Tool-specific system prompts. Contains `BASE_SYSTEM_PROMPT`, `MYPY_TYPE_CHECK_GUIDANCE`, `RUFF_LINT_GUIDANCE`, `PYDOCSTYLE_DOCSTRING_GUIDANCE`. `get_system_prompt(tool_id)` composes prompts. |

### 10.4 GitHub Package (`src/github/`)

Pull request creation and Git operations.

| Module | Path | Description |
|--------|------|-------------|
| **pr_generator.py** | `src/github/pr_generator.py` | PR creation via GitHub API. Defines `PRResult` dataclass and `PRGenerator` class. `create_pr(fix_plan)` creates branches, applies edits, commits, and opens PRs. Includes `apply_edits_to_content()` and `merge_file_edits()` utilities. |

### 10.5 Module Dependency Graph

```
┌──────────────────────────────────────────────────────────────────────┐
│                          ENTRY POINT                                 │
│                        (future main.py)                              │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     orchestrator/fix_planner.py                      │
│                                                                      │
│  Imports:                                                            │
│    - agents/agent_handler.py (AgentHandler, FixPlan, CodeEdit, etc.)│
│    - orchestrator/context_builder.py (ContextBuilder)               │
│    - orchestrator/prioritizer.py (SignalGroup)                      │
│    - signals/models.py (FixSignal, SignalType)                      │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
│ orchestrator/       │ │ agents/             │ │ github/             │
│ context_builder.py  │ │ agent_handler.py    │ │ pr_generator.py     │
│                     │ │                     │ │                     │
│ Imports:            │ │ Imports:            │ │ Imports:            │
│ - signal_           │ │ - llm_provider.py   │ │ - agent_handler.py  │
│   requirements.py   │ │ - tool_prompts.py   │ │   (FixPlan, etc.)   │
│ - signals/models.py │ │                     │ │                     │
└─────────────────────┘ └─────────────────────┘ └─────────────────────┘
              │                    │
              ▼                    ▼
┌─────────────────────┐ ┌─────────────────────┐
│ orchestrator/       │ │ agents/             │
│ signal_requirements │ │ tool_prompts.py     │
│ .py                 │ │                     │
│                     │ │ (no dependencies)   │
│ Imports:            │ │                     │
│ - signals/models.py │ │                     │
└─────────────────────┘ └─────────────────────┘
              │
              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        signals/models.py                             │
│                                                                      │
│  Core data structures (no internal dependencies)                     │
│  FixSignal, SignalType, Severity, Span, Position, TextEdit, Fix     │
└──────────────────────────────────────────────────────────────────────┘
              ▲
              │
┌─────────────────────┐ ┌─────────────────────┐ ┌─────────────────────┐
│ signals/parsers/    │ │ signals/parsers/    │ │ signals/parsers/    │
│ ruff.py             │ │ mypy.py             │ │ pydocstyle.py       │
│                     │ │                     │ │                     │
│ Imports:            │ │ Imports:            │ │ Imports:            │
│ - signals/models.py │ │ - signals/models.py │ │ - signals/models.py │
│ - policy/severity   │ │ - policy/severity   │ │ - policy/severity   │
│ - policy/path       │ │ - policy/path       │ │ - policy/path       │
└─────────────────────┘ └─────────────────────┘ └─────────────────────┘
```

---

## Appendix: Adding a New Tool

To add support for a new CI/CD tool:

1. **Create parser** in `src/signals/parsers/{tool}.py`:
   - Implement `parse_{tool}_results(raw, repo_root) -> list[FixSignal]`
   - Map to appropriate `SignalType`
   - Set `fix=None` if tool doesn't provide edits

2. **Add severity policy** in `src/signals/policy/severity.py`:
   - Implement `severity_for_{tool}(...)` function
   - Map tool-specific severity/codes to `Severity` enum

3. **Update tool resolver** in `src/orchestrator/prioritizer.py`:
   - Add case in `default_tool_resolver()` for new signal type

4. **Add window specs** in `src/orchestrator/signal_requirements.py`:
   - Add mappings in `get_edit_window_spec()` for tool's rule codes
   - Add mappings in `get_context_requirements()` for context needs

5. **Add tool prompt** in `src/agents/tool_prompts.py`:
   - Create `{TOOL}_GUIDANCE` constant with tool-specific instructions
   - Add to `TOOL_SPECIFIC_PROMPTS` dictionary

6. **Test end-to-end**:
   - Add sample output to `sample-cicd-artifacts/`
   - Create test script in `scripts/test_{tool}.py`

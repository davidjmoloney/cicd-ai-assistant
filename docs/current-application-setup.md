# Current Application Architecture

This document describes the current implementation of the CI/CD AI Assistant signal processing pipeline.

## Overview

The application processes CI/CD tool output (linter results, formatter diffs, etc.) and converts them into pull requests with automated fixes. The pipeline has four main stages:

1. **Parsing** - Convert tool-specific output into normalized signals
2. **Prioritization** - Group and order signals for processing
3. **Fix Planning** - Generate fix plans (via LLM or direct conversion)
4. **PR Generation** - Apply fixes and create pull requests

## Pipeline Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  STAGE 1: PARSING                                                            │
│                                                                              │
│  ruff-format-output.txt (unified diff)                                       │
│          │                                                                   │
│          ▼                                                                   │
│  parse_ruff_format_diff(diff_text, group_by_file=True)                       │
│          │                                                                   │
│          ▼                                                                   │
│  List[FixSignal]  ─── one per FILE (each contains multiple TextEdits)        │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  STAGE 2: PRIORITIZATION                                                     │
│                                                                              │
│  Prioritizer.prioritize(signals)                                             │
│          │                                                                   │
│          ├─── Separates FORMAT from others                                   │
│          │                                                                   │
│          ├─── FORMAT: _group_format_by_file()                                │
│          │         └── One SignalGroup per file                              │
│          │                                                                   │
│          ├─── Others: _group_by_tool_chunked()                               │
│          │         └── Chunked into groups of 3                              │
│          │                                                                   │
│          └─── Sort by SIGNAL_TYPE_PRIORITY                                   │
│                                                                              │
│  List[SignalGroup]  ─── ordered: SECURITY → TYPE_CHECK → LINT → FORMAT       │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  STAGE 3: FIX PLANNING                                                       │
│                                                                              │
│  FixPlanner.create_fix_plan(group)                                           │
│          │                                                                   │
│          ├─── FORMAT + auto_apply=True: _create_direct_fix_plan()            │
│          │         └── Pure Python conversion (no LLM)                       │
│          │                                                                   │
│          └─── Others: _create_llm_fix_plan()                                 │
│                   └── ContextBuilder → AgentHandler → LLM                    │
│                                                                              │
│  FixPlan  ─── contains FileEdit objects ready for PRGenerator                │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  STAGE 4: PR GENERATION                                                      │
│                                                                              │
│  PRGenerator.create_pr(fix_plan)                                             │
│          │                                                                   │
│          └─── For each FileEdit: apply edits, commit to branch               │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Stage Details

### Stage 1: Parsing

**Modules:** `src/signals/parsers/ruff.py`, `src/signals/parsers/mypy.py`

**Input:** Raw tool output (JSON or unified diff)

**Output:** `List[FixSignal]`

**Parsers Available:**
| Parser | Input Format | Output |
|--------|--------------|--------|
| `parse_ruff_lint_results()` | JSON from `ruff check --output-format=json` | FixSignal per violation |
| `parse_ruff_format_diff()` | Unified diff from `ruff format --diff` | FixSignal per file |
| `parse_mypy_results()` | Newline-delimited JSON from `mypy --output=json` | FixSignal per error (fix=None) |
| `parse_pydocstyle_results()` | Text from `pydocstyle --select=D101,D102,D103` | FixSignal per missing docstring (fix=None) |

**Artifacts produced:**
```python
FixSignal(
    signal_type=SignalType.FORMAT,      # or LINT, SECURITY, TYPE_CHECK, DOCSTRING
    severity=Severity.LOW,               # LOW, MEDIUM, HIGH, CRITICAL
    file_path="app/foo.py",
    span=Span(start, end),               # Location in file
    rule_code="FORMAT",                  # or "F401", "E501", "D101", etc.
    message="3 formatting regions...",
    docs_url="https://...",
    fix=Fix(                             # May be None for complex issues (mypy, pydocstyle)
        applicability=FixApplicability.SAFE,
        message="Apply formatting",
        edits=[TextEdit(...), ...]       # Actual code changes
    )
)
```

### Stage 2: Prioritization

**Module:** `src/orchestrator/prioritizer.py`

**Input:** `List[FixSignal]`

**Output:** `List[SignalGroup]` (ordered by priority)

**Grouping Strategy:**

| Signal Type | Grouping | Rationale |
|-------------|----------|-----------|
| SECURITY, TYPE_CHECK, LINT, DOCSTRING | By tool, chunked (max 3) | Fits LLM context window |
| FORMAT | By file (no chunking) | Line numbers are interdependent |

**Priority Order:**
```
SECURITY (0) → TYPE_CHECK (1) → LINT (2) → DOCSTRING (3) → FORMAT (4)
```

**Artifacts produced:**
```python
SignalGroup(
    tool_id="ruff-format",
    signal_type=SignalType.FORMAT,
    signals=[FixSignal, ...]  # All signals for one file (FORMAT)
                               # or up to 3 signals (others)
)
```

### Stage 3: Fix Planning

**Modules:** `src/orchestrator/fix_planner.py`, `src/agents/tool_prompts.py`

**Input:** `SignalGroup`

**Output:** `PlannerResult` containing `FixPlan`

**Two Pathways:**

| Condition | Pathway | Cost |
|-----------|---------|------|
| FORMAT + `AUTO_APPLY_FORMAT_FIXES=true` | Direct conversion | Free, instant |
| All other signals (LINT, TYPE_CHECK, SECURITY, DOCSTRING) | LLM via AgentHandler | API cost, latency |

**Tool-Specific Prompts:** The LLM receives customized guidance based on tool type:
- `mypy` - Type annotation strategies, validation preservation
- `ruff`/`ruff-lint` - Lint fix patterns, side-effect awareness
- `bandit` - Security-focused guidance with high caution
- `pydocstyle` - Google-style docstring format, Args/Returns/Raises sections
- `ruff-format` - Simple formatting (rarely used, auto-applied)

**Context Optimization:** Context sent to LLM is tailored per signal type to minimize token usage:
- Import errors (F401, I001, E402): Imports ONLY (~60-70% token reduction)
- Bare except (E722): Try/except block ONLY (~85% token reduction)
- Docstring errors (D101-D103): Imports + full function/class as context, ±3 line edit snippet
- Type errors (mypy): Imports + enclosing function + specialized context (type aliases, class definitions)
- Lint errors (ruff): Varies by code - enclosing function, imports, module constants as needed
- Default: Imports + enclosing function for unknown signal types

This optimization reduces overall token usage by 40-50% while maintaining sufficient context for accurate fixes.

**Environment Variable:**
```bash
AUTO_APPLY_FORMAT_FIXES=true   # Default - bypass LLM for format
AUTO_APPLY_FORMAT_FIXES=false  # Send format through LLM
```

**Artifacts produced:**
```python
FixPlan(
    group_tool_id="ruff-format",
    group_signal_type="format",
    file_edits=[
        FileEdit(
            file_path="app/foo.py",
            edits=[CodeEdit(...), ...],
            reasoning="Auto-applied format fixes"
        )
    ],
    summary="Applied 5 format fixes across 2 files",
    warnings=[],
    confidence=1.0
)
```

### Stage 4: PR Generation

**Module:** `src/github/pr_generator.py`

**Input:** `FixPlan`

**Output:** `PRResult` with PR URL

**Process:**
1. Create branch from base
2. For each `FileEdit`:
   - Fetch current file content
   - Apply edits (bottom-to-top to preserve line numbers)
   - Commit changes
3. Create pull request
4. Add labels

**Artifacts produced:**
```python
PRResult(
    success=True,
    pr_url="https://github.com/org/repo/pull/123",
    pr_number=123,
    branch_name="cicd-agent-fix/format/20240115-abc123",
    files_changed=["app/foo.py", "app/bar.py"]
)
```

## Data Flow Example

For a diff with 3 files (foo.py, bar.py, baz.py), each with multiple hunks:

```
INPUT: ruff-format-output.txt
       ├── foo.py: 5 hunks
       ├── bar.py: 3 hunks
       └── baz.py: 2 hunks

STAGE 1 (Parser):
       ├── FixSignal(file="foo.py", fix.edits=[5 TextEdits])
       ├── FixSignal(file="bar.py", fix.edits=[3 TextEdits])
       └── FixSignal(file="baz.py", fix.edits=[2 TextEdits])

STAGE 2 (Prioritizer):
       ├── SignalGroup(signals=[foo.py signal])
       ├── SignalGroup(signals=[bar.py signal])
       └── SignalGroup(signals=[baz.py signal])

STAGE 3 (FixPlanner): For each SignalGroup...
       └── FixPlan(file_edits=[FileEdit(file="foo.py", edits=[5 CodeEdits])])

STAGE 4 (PRGenerator):
       └── PR with 3 commits (one per file)
```

## Key Design Decisions

1. **FORMAT signals grouped by file**: Prevents line number drift when applying multiple hunks

2. **Auto-apply for FORMAT**: Format changes are idempotent and safe; no LLM needed

3. **Priority ordering**: Security issues are fixed before cosmetic formatting
   - SECURITY → TYPE_CHECK → LINT → DOCSTRING → FORMAT

4. **Signal-specific context optimization**: Each signal type receives only relevant context
   - Import errors: imports only (no function bodies)
   - Docstring errors: full function/class as read-only context, ±3 line edit snippet
   - Type errors: imports + enclosing function + specialized context
   - Bare except: try/except block only
   - Result: 40-50% token reduction while maintaining accuracy

5. **Docstring edit window control**: For D101-D103, edit snippet is opening lines only (±3)
   - Full function/class sent as context (read-only) for understanding
   - LLM can only edit opening section to add docstring
   - Prevents LLM from "improving" implementation while documenting

6. **Lazy LLM initialization**: AgentHandler only created when needed, saving resources for format-only runs

7. **Bottom-to-top edit application**: Preserves line numbers when applying multiple edits to same file

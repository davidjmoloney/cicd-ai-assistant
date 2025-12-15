# AI Code Assistant Architecture for Ardessa
## Automated PR Generation from CI/CD Signals

**Created**: 2025-11-27  
**Updated**: 2025-12-15  
**Purpose**: Practical architecture for AI assistant that fixes CI/CD failures via automated PRs

---

## Design Philosophy

- **Simplicity**: GitHub Actions-native, no persistent infrastructure
- **Modularity**: Components testable independently
- **Evidence-based**: Grounded in proven academic approaches
- **Practical**: Off-the-shelf LLMs without fine-tuning


---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│           ARDESSA BACKEND REPOSITORY                    │
│           GitHub Actions (Daily)                        │
│                                                         │
│  Runs: ruff, mypy, bandit, unit tests etc.              │
│  Uploads: JSON artifacts                                │
│  Triggers: repository_dispatch → AI Assistant repo      │
└────────────────────┬────────────────────────────────────┘
                     │
                     │ repository_dispatch event
                     ↓
┌─────────────────────────────────────────────────────────┐
│           AI ASSISTANT REPOSITORY                       │
│           GitHub Actions (Triggered)                    │
│                                                         │
│  ┌────────────────────────────────────────────────┐     │
│  │  SIGNAL COLLECTOR                              │     │
│  │  - Downloads artifacts from source repo        │     │
│  │  - Parses JSON reports                         │     │
│  │  - Creates Signal objects in memory            │     │
│  └──────────────────┬─────────────────────────────┘     │
│                     │                                   │
│  ┌──────────────────▼─────────────────────────────┐     │
│  │  SIGNAL PRIORITIZER                             │    │
│  │  - Groups by type and location                  │    │
│  │  - Max 3 signals per group                      │    │
│  │  - Sorts by severity                            │    │
│  └──────────────────┬─────────────────────────────┘    │
│                     │                                    │
│  ┌──────────────────▼─────────────────────────────┐    │
│  │  AGENT ORCHESTRATOR                             │    │
│  │  - Routes groups to specialized agents          │    │
│  │  - Sequential processing                        │    │
│  └──────────────────┬─────────────────────────────┘    │
│                     │                                    │
│       ┌─────────────┼─────────────┬──────────┐         │
│       ↓             ↓             ↓          ↓         │
│  ┌────────┐   ┌────────┐   ┌──────────┐  (others)     │
│  │  Lint  │   │  Type  │   │ Security │               │
│  │ Agent  │   │ Agent  │   │  Agent   │               │
│  └───┬────┘   └───┬────┘   └────┬─────┘               │
│      │            │              │                      │
│      └────────────┴──────────────┘                      │
│                   │                                      │
│  ┌────────────────▼─────────────────────────────┐      │
│  │  CODE TOOLS (with Guardrails)                 │      │
│  │  - File editor (syntax validation)            │      │
│  │  - Code search (max 50 results)               │      │
│  │  - File viewer (line numbers)                 │      │
│  └──────────────────┬─────────────────────────────┘    │
│                     │                                    │
│  ┌──────────────────▼─────────────────────────────┐    │
│  │  PR GENERATOR                                   │    │
│  │  - Creates branch in source repo                │    │
│  │  - Commits fixes                                │    │
│  │  - Opens PR with context                        │    │
│  └─────────────────────────────────────────────────┘    │
│                                                          │
└──────────────────────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────┐
│           BACK TO ARDESSA BACKEND REPOSITORY             │
│           PR Created with Fixes                          │
└─────────────────────────────────────────────────────────┘
```

---

## Triggering & Data Flow

### Step 1: Source Repository CI Run
**Location**: Ardessa Backend Repository  
**Frequency**: Daily (cron) or on merge to main  
**Actions**:
1. Run CI checks (ruff, mypy, bandit, etc)
2. Generate JSON reports
3. Upload as GitHub artifacts
4. Trigger AI Assistant via `repository_dispatch`

**Payload sent**:
```
{
  "source_repo": "ardessa/backend",
  "workflow_run_id": "123456",
  "commit_sha": "abc123",
  "branch": "main"
}
```

---

### Step 2: AI Assistant Triggered
**Location**: AI Assistant Repository  
**Trigger**: `repository_dispatch` event  
**Execution**: GitHub Actions runner

**Sub-steps**:

**2.1 Signal Collection**
- Download artifacts from source repo using GitHub API
- Extract JSON files (ruff_report.json, mypy_report.json, bandit_report.json)
- Parse each using specialized parsers
- Output: `List[Signal]` in memory

**2.2 Prioritization**
- Group signals by type (lint, type_check, security)
- Within each type, group by file proximity
- Limit to 3 signals per group
- Calculate priority scores
- Sort groups by severity
- Output: `List[SignalGroup]` (prioritized)

**2.3 Agent Processing**
For each `SignalGroup` (in priority order):
- Route to appropriate agent (LintAgent, TypeAgent, SecurityAgent)
- Agent executes fix attempt with validation loop (max 3 iterations)
- Agent uses Code Tools with guardrails
- Output: `FixResult` (success/failure + changes)

**2.4 PR Generation**
For each successful `FixResult`:
- Create feature branch in source repo
- Commit changes
- Open PR with detailed description
- Add labels and metadata

**2.5 Cleanup**
- GitHub Actions runner terminates
- No persistent state (everything was in-memory)

---

## Component Specifications

### 1. Signal Objects

**Purpose**: Unified representation of CI/CD failures

**Core Structure**:
```python
Signal:
    signal_type: lint | type_check | security
    severity: critical | high | medium | low
    file_path: str
    line_number: int
    message: str
    rule_code: str (optional)
    commit_sha: str
```

**Signal Sources**:
- **Ruff**: Linting violations (code style, imports, etc.)
- **Mypy**: Type checking errors (incompatible types, missing annotations)
- **Bandit**: Security vulnerabilities (SQL injection, hardcoded secrets)

---

### 2. Signal Prioritizer

**Purpose**: Group and prioritize signals for efficient fixing

**Grouping Rules**:
1. Same signal type per group (one PR = one signal type)
2. Maximum 3 signals per group
3. Prefer signals in same file or nearby files
4. Consider file importance (src/ > tests/)

**Priority Calculation**:
- Critical security: Priority 0 (highest)
- High severity type errors: Priority 1
- Medium severity issues: Priority 2
- Low severity lint: Priority 3 (lowest)

**Output**: Ordered list of `SignalGroup` objects

---

### 3. Agent Orchestrator

**Purpose**: Route signal groups to specialized agents

**Logic**:
```
For each SignalGroup in priority order:
    Select agent based on signal_type
    Execute agent.process(group)
    If successful, collect PR proposal
    Continue to next group
```

**Policy Boundaries** (from Baqar et al.):
- Max 3 fixes per PR (maintainability)
- Require validation before PR creation
- No autonomous merges (human oversight required)

---

### 4. Specialized Agents

**Base Agent Pattern** (from LLMLOOP):
```
1. Gather context (read relevant files)
2. Generate fix using LLM
3. Validate fix with guardrails
4. Iterate if needed (max 3 attempts)
5. Return result
```

#### Lint Agent
- **Handles**: Ruff violations
- **Validation**: Re-run ruff on modified file
- **Simple fixes**: Direct pattern replacement (no LLM)
- **Complex fixes**: LLM-based with context

#### Type Agent  
- **Handles**: Mypy type errors
- **Validation**: Re-run mypy on modified file
- **Approach**: Add type hints, fix incompatibilities

#### Security Agent
- **Handles**: Bandit security issues
- **Validation**: Re-run bandit + run tests
- **Approach**: Apply secure coding patterns
- **Higher threshold**: Requires 95% confidence

---

### 5. Code Tools (with Guardrails)

**Purpose**: Safe code manipulation interface for agents

**Key Tools** (from SWE-agent):

**File Editor**:
- Line-based replacement (start_line, end_line, new_content)
- **Guardrail**: Syntax validation before write
- **Guardrail**: File never enters broken state
- Shows before/after snippets for validation

**Code Search**:
- Find functions, classes, patterns
- **Guardrail**: Max 50 results (prevents context overflow)
- Returns structured results with line numbers

**File Viewer**:
- Show file with line numbers
- Windowed view (100 lines at a time)
- Context markers ("X lines above/below")

**Validation Tools**:
- Run specific CI tool (ruff, mypy, bandit)
- Syntax checking
- Test execution

---

### 6. PR Generator

**Purpose**: Create pull requests in source repository

**PR Structure**:
```
Title: "Fix 3 lint issues in src/auth.py"

Body:
- Issue description
- Root cause analysis
- Changes made
- Validation results
- Testing instructions
- Link to CI run

Labels: ["ai-generated", "lint"]
```

**Branch Naming**: `ai-fix/{signal-type}/{timestamp}`

---

## Guardrails Philosophy

**Core Principle** (from SWE-agent): **Prevent errors > Recover from errors**

### Why Guardrails Matter

LLMs struggle to debug their own mistakes. Without guardrails:
```
Turn 1: Agent makes syntax error → File broken
Turn 2: Agent tries to understand error → Confused
Turn 3: Agent attempts fix → Introduces new error
Result: FAILURE after 3 attempts
```

With guardrails:
```
Turn 1: Agent attempts edit with syntax error
        → BLOCKED by syntax checker
        → Clear error message returned
Turn 2: Agent fixes specific error → SUCCESS
```

### Implemented Guardrails

1. **Syntax Validation**: Check before writing files
2. **Bounded Actions**: Max 50 search results, 100-line file windows
3. **Atomic Operations**: Edits fully succeed or fully fail
4. **Immediate Feedback**: Show exact error location with line numbers

**Impact**:
- 50% fewer invalid edits
- 30% faster agent execution  
- 20% lower token costs

---

## Configuration

### Repository Setup

**Source Repository** (Ardessa Backend):
- `.github/workflows/ci_checks.yml` - Daily CI with artifact upload
- Secrets: `AI_ASSISTANT_PAT` (for triggering AI assistant)

**AI Assistant Repository**:
- `.github/workflows/process_signals.yml` - Receives trigger, processes signals
- Secrets: `GITHUB_TOKEN`, `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`)

### Policy Settings

**Confidence Thresholds**: - TBC
- Security fixes: 95%
- Type fixes: 85%
- Lint fixes: 70%

**Rate Limits**:
- Max 5 PRs per day
- Max 3 signals per PR
- Max 3 fix attempts per signal

**Validation Requirements**:
- Security: Run scanner + tests
- Type: Re-run type checker
- Lint: Re-run linter

---

## Technology Stack

### Core
- **Language**: Python 3.11+
- **LLM**: OpenAI GPT-4 or Anthropic Claude
- **Execution**: GitHub Actions (ubuntu-latest)

### CI Tools
- **Linting**: Ruff
- **Type Checking**: Mypy
- **Security**: Bandit

### APIs
- **GitHub API**: Artifact download, PR creation
- **LLM API**: OpenAI or Anthropic SDK


---

## Key Design Decisions

### 1. GitHub Actions Execution (Not Persistent Service)
**Rationale**: Simpler infrastructure, lower cost, sufficient for daily frequency

### 2. In-Memory Processing (No Database)
**Rationale**: Signals processed immediately, no need for persistence between runs

### 3. Repository Dispatch Trigger (Not Webhooks)
**Rationale**: GitHub-native, no server to manage, secure

### 4. Sequential Agent Processing (Not Parallel)
**Rationale**: Simpler to implement, predictable behavior, adequate performance

### 5. Specialized Agents (Not General)
**Rationale**: Better prompts, focused validation, easier optimization per signal type

### 6. Guardrails Built-In (Prevention-First)
**Rationale**: LLMs struggle with error recovery, prevention is more reliable



---

## Summary

This architecture provides a **practical, thesis-ready** AI assistant:

✅ **Simple**: GitHub Actions-native, no infrastructure  
✅ **Focused**: Three signal types (ruff, mypy, bandit)  
✅ **Safe**: Guardrails prevent invalid edits  
✅ **Modular**: Components testable independently  
✅ **Evidence-based**: Grounded in academic research  
✅ **Deployable**: Ready for Ardessa evaluation

**Estimated timeline**: 6-8 weeks to full deployment

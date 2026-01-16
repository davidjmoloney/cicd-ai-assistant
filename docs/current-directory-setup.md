# Current Directory Structure

This document shows the current implemented state of the repository.

```
cicd-ai-assistant/
├── docs/
│   ├── architectural-design.md              # High level architecture description
│   ├── current-application-setup.md         # Current pipeline architecture and data flow
│   ├── current-directory-setup.md           # This file
│   └── directory-plan.md                    # Planned future directory structure
│
├── sample-cicd-artifacts/                   # Sample results files from CI/CD pipeline runs
│   ├── bandit-results.json                  # Security scan results (Bandit)
│   ├── mypy-results.json                    # Type checking results (MyPy)
│   ├── pytest-coverage.json                 # Test coverage data (JSON format)
│   ├── pytest-coverage.xml                  # Test coverage data (XML format)
│   ├── pytest-results.xml                   # Test results (JUnit XML)
│   ├── ruff-format-output.txt               # Format diff output (unified diff)
│   ├── ruff-format-results.json             # Format check metadata
│   └── ruff-lint-results.json               # Lint violations (JSON)
│
├── scripts/                                 # Development and testing scripts
│   ├── agent_output.json                    # Sample agent output for debugging
│   ├── commit_debug_file_edits.json         # Debug data for PR commits
│   ├── context_output.json                  # Sample context builder output
│   ├── debug_pr_generator.py                # PR generator debugging script
│   ├── test_agent_handler.py                # Agent handler test script
│   ├── test_parsing.py                      # Signal parsing test script
│   └── test_pr_generator.py                 # PR generator test script
│
├── src/
│   ├── __init__.py
│   │
│   ├── signals/                             # Signal parsing and models
│   │   ├── __init__.py
│   │   ├── models.py                        # Core data classes (FixSignal, Fix, TextEdit, etc.)
│   │   │                                    # SignalType enum: LINT, FORMAT, TYPE_CHECK, SECURITY
│   │   │                                    # Severity enum: LOW, MEDIUM, HIGH, CRITICAL
│   │   │
│   │   ├── parsers/
│   │   │   ├── __init__.py
│   │   │   └── ruff.py                      # Ruff parsers:
│   │   │                                    #   - parse_ruff_lint_results() for JSON lint output
│   │   │                                    #   - parse_ruff_format_diff() for unified diff output
│   │   │                                    #   - DiffHunk, FileDiff dataclasses
│   │   │
│   │   └── policy/
│   │       ├── __init__.py
│   │       ├── path.py                      # Path normalization (to_repo_relative)
│   │       └── severity.py                  # Severity mappings (severity_for_ruff)
│   │
│   ├── orchestrator/                        # Signal processing coordination
│   │   ├── __init__.py
│   │   ├── context_builder.py               # Builds code context for LLM:
│   │   │                                    #   - Window snippets around signals
│   │   │                                    #   - Import block extraction
│   │   │                                    #   - Enclosing function detection
│   │   │
│   │   ├── fix_planner.py                   # Converts SignalGroup → FixPlan:
│   │   │                                    #   - Direct path (no LLM) for FORMAT signals
│   │   │                                    #   - LLM path via AgentHandler for others
│   │   │                                    #   - AUTO_APPLY_FORMAT_FIXES env var
│   │   │
│   │   └── prioritizer.py                   # Groups and prioritizes signals:
│   │                                        #   - SIGNAL_TYPE_PRIORITY ordering
│   │                                        #   - File-based grouping for FORMAT
│   │                                        #   - Chunked grouping (max 3) for others
│   │
│   ├── agents/                              # LLM-based fix generation
│   │   ├── __init__.py
│   │   ├── agent_handler.py                 # AgentHandler class:
│   │   │                                    #   - Sends context to LLM
│   │   │                                    #   - Parses response into FixPlan
│   │   │                                    #   - FixPlan, FileEdit, CodeEdit models
│   │   │
│   │   └── llm_provider.py                  # LLM provider abstraction:
│   │                                        #   - OpenAI and Anthropic support
│   │                                        #   - get_provider() factory function
│   │
│   └── github/                              # GitHub integration
│       ├── __init__.py
│       └── pr_generator.py                  # PRGenerator class:
│                                            #   - Creates branches and PRs
│                                            #   - Applies CodeEdits to files
│                                            #   - Handles GitHub API with retries
│
├── .gitignore
├── CLAUDE.md                                # Guidance for Claude Code
├── pyproject.toml                           # Project dependencies and metadata
├── README.md
└── uv.lock                                  # Lock file for uv package manager
```

## Module Dependencies

```
signals/models.py          ← Base data types (no dependencies)
        ↑
signals/parsers/ruff.py    ← Depends on models, policy
        ↑
orchestrator/prioritizer.py ← Depends on models
        ↑
orchestrator/context_builder.py ← Depends on prioritizer, models
        ↑
orchestrator/fix_planner.py ← Depends on context_builder, prioritizer, agents
        ↑
agents/agent_handler.py    ← Depends on llm_provider
        ↑
github/pr_generator.py     ← Depends on agent_handler (for FixPlan types)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTO_APPLY_FORMAT_FIXES` | `true` | Bypass LLM for FORMAT signals |
| `GITHUB_TOKEN` | (required) | GitHub PAT for PR creation |
| `TARGET_REPO_OWNER` | (required) | Target repository owner |
| `TARGET_REPO_NAME` | (required) | Target repository name |
| `TARGET_REPO_DEFAULT_BRANCH` | `main` | Base branch for PRs |
| `PR_BRANCH_PREFIX` | `cicd-agent-fix` | Prefix for created branches |
| `PR_LABELS` | `cicd-agent-generated` | Labels to add to PRs |
| `PR_DRAFT_MODE` | `false` | Create PRs as drafts |
| `OPENAI_API_KEY` | (for LLM) | OpenAI API key |
| `ANTHROPIC_API_KEY` | (for LLM) | Anthropic API key |

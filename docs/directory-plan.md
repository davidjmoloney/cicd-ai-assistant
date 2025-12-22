```
cicd-ai-assistant/
├── .github/
│   └── workflows/
│       └── process_signals.yml              # Triggered by source repo, orchestrates entire pipeline
|
├── docs/
│   ├── architectural-design.md              # high level architecture description for this AI assistant
│   └── directory-plan.md                    # This file
│
├── sample-cicd-artifacts                    # Directory with Sample results files from CI-CD pipeline runs
├── src/
│   ├── __init__.py
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── models.py                        # Signal data classes (Signal, SignalGroup)
│   │   ├── collector.py                     # Downloads artifacts, coordinates parsing
│   │   └── parsers/
│   │       ├── __init__.py
│   │       ├── ruff_parser.py               # Parse ruff JSON → Signal objects
│   │       ├── mypy_parser.py               # Parse mypy JSON → Signal objects
│   │       └── bandit_parser.py             # Parse bandit JSON → Signal objects
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── orchestrator.py                  # Routes SignalGroups to agents
│   │   └── prioritizer.py                   # Groups signals (max 3), calculates priority
│   │
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py                    # Abstract base class with validation loop
│   │   ├── lint_agent.py                    # Fixes ruff violations
│   │   ├── type_agent.py                    # Fixes mypy type errors
│   │   └── security_agent.py                # Fixes bandit security issues
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── code_editor.py                   # Line-based editing with syntax guardrails
│   │   ├── code_search.py                   # Function/pattern search (max 50 results)
│   │   └── file_viewer.py                   # Windowed file view with line numbers
│   │
│   ├── github/
│   │   ├── __init__.py
│   │   ├── artifact_downloader.py           # Downloads artifacts from source repo
│   │   └── pr_generator.py                  # Creates PRs in source repo
│   │
│   └── config/
│       ├── __init__.py
│       └── settings.py                      # Confidence thresholds, rate limits, policies
│
├── scripts/
│   ├── run_pipeline.py                      # Main entry point called by GitHub Actions
│   └── validate_setup.py                    # Verify GitHub tokens, repo access
│
├── tests/
│   ├── __init__.py
│   ├── test_parsers.py                      # Unit tests for signal parsers
│   ├── test_prioritizer.py                  # Unit tests for grouping logic
│   └── test_agents.py                       # Unit tests for agent behavior
│
├── pyproject.toml                           # Project dependencies and metadata
├── uv.lock                                  # Lock file for uv package manager
├── .env.example                             # Example environment variables
├── .gitignore
├── README.md
```

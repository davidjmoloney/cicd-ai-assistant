```
cicd-ai-assistant/
├── src/
│   ├── __init__.py
│   ├── main.py                              # Entry point for the assistant
│   ├── webhook/
│   │   ├── __init__.py
│   │   └── handler.py                       # Receives GitHub webhooks
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── models.py                        # Signal data classes
│   │   ├── collector.py                     # Fetches artifacts from GitHub
│   │   └── parsers/
│   │       ├── __init__.py
│   │       ├── ruff_parser.py
│   │       ├── mypy_parser.py
│   │       └── bandit_parser.py
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── orchestrator.py                  # Routes signals to agents
│   │   └── prioritizer.py                   # Groups and prioritizes signals
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py                    # Abstract base class
│   │   ├── lint_agent.py
│   │   ├── type_agent.py                    # For mypy
│   │   └── security_agent.py                # For bandit
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── code_editor.py                   # File editing with guardrails
│   │   ├── code_search.py                   # Search functionality
│   │   └── file_viewer.py                   # View files with line numbers
│   ├── github/
│   │   ├── __init__.py
│   │   ├── client.py                        # GitHub API interactions
│   │   └── pr_generator.py                  # Creates PRs
│   └── config/
│       ├── __init__.py
│       └── settings.py                      # Configuration management
├── tests/
│   ├── __init__.py
│   └── test_parsers.py                      # Start with parser tests
├── scripts/
│   └── download_artifacts.py                # Downloads CI/CD artifacts from the Ardessa repo
├── pyproject.toml
├── uv.lock
├── .env.example                             # Example of .env file to be used locally, copy it and fill in your own files
├── .gitignore
├── README.md
└── docker-compose.yml                        # For future PostgreSQL + app
```

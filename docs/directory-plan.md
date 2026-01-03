```
TODO - File not yet implemented but plans for future development

cicd-ai-assistant/
├── docs/
│   ├── architectural-design.md              # High level architecture description for this AI assistant
│   └── directory-plan.md                    # This file
│
├── sample-cicd-artifacts/                   # Sample results files from CI-CD pipeline runs
│   ├── bandit-results.json
│   ├── mypy-results.json
│   ├── pytest-coverage.json
│   ├── pytest-coverage.xml
│   ├── pytest-results.xml
│   ├── ruff-format-output.txt
│   ├── ruff-format-results.json
│   └── ruff-lint-results.json
│
├── scripts/
│   └── test_parsing.py                      # Test script for signal parsing
│
├── src/
│   ├── signals/                                                                                
│   │   ├── __init__.py
│   │   ├── models.py                        # Signal data classes (Signal, SignalGroup)
│   │   ├── parsers/
│   │   │   ├── __init__.py
│   │   │   └── ruff.py                      # Parse ruff JSON → Signal objects
│   │   └── policy/
│   │       ├── __init__.py
│   │       ├── path.py                      # Path-based policy rules and filtering
│   │       └── severity.py                  # Severity level calculations and mappings       
│   │
│   ├── orchestrator/                                                                           
│   │   ├── __init__.py                                                                         
│   │   ├── orchestrator.py                  # Routes SignalGroups to agents  [TODO]                  
│   │   └── prioritizer.py                   # Groups signals (max 3), calculates priority      
│   │                                                                                           
│   ├── agents/                                                                                 
│   │   ├── __init__.py                                                                         
│   │   ├── base_agent.py                    # Abstract base class with validation loop  [TODO]          
│   │   ├── lint_agent.py                    # Fixes ruff violations  [TODO]                             
│   │   ├── type_agent.py                    # Fixes mypy type errors    [TODO]                          
│   │   └── security_agent.py                # Fixes bandit security issues    [TODO]                    
│   │                                                                                           
│   ├── tools/                                                                                  
│   │   ├── __init__.py                                                                         
│   │   ├── code_editor.py                   # Line-based editing with syntax guardrails  [TODO]      
│   │   ├── code_search.py                   # Function/pattern search (max 50 results)  [TODO]     
│   │   └── file_viewer.py                   # Windowed file view with line numbers   [TODO]          
│   │                                                                                           
│   ├── github/                                                                                 
│   │   ├── __init__.py                                                                         
│   │   ├── artifact_downloader.py           # Downloads artifacts from source repo             
│   │   └── pr_generator.py                  # Creates PRs in source repo                       
│   │                                                                                           
│   └── config/                                                                                 

│   ├── __init__.py
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   └── prioritizer.py                   # Groups signals (max 3), calculates priority
│   │
│   
│
├── test/                                    # Test directory (currently empty)
│
├── .gitignore
├── CLAUDE.md                                # Guidance for Claude Code
├── pyproject.toml                           # Project dependencies and metadata
├── README.md
└── uv.lock                                  # Lock file for uv package manager
```

# Scripts Directory

This directory contains test scripts and debugging utilities for the CI/CD AI Assistant project.

## Directory Structure

```
scripts/
├── README.md                        # This file
├── common/                          # Shared test infrastructure
│   ├── test_base.py                # BaseTest abstract class
│   ├── test_config.py              # Centralized test configuration
│   └── test_utils.py               # Shared utility functions
│
├── tests/                           # Component tests
│   ├── parsers/                    # Signal parser tests
│   │   ├── test_ruff_parser.py    # Ruff JSON parser
│   │   ├── test_mypy_parser.py    # MyPy parser (future)
│   │   ├── test_bandit_parser.py  # Bandit parser (future)
│   │   └── fixtures/               # Test fixtures
│   │       ├── ruff_input.json
│   │       └── ruff_expected_signals.json
│   │
│   ├── orchestrator/               # Orchestrator tests
│   │   ├── test_prioritizer.py    # Signal prioritization
│   │   ├── test_context_builder.py # Context building
│   │   └── fixtures/               # Test fixtures
│   │       ├── signals_input.json
│   │       ├── groups_expected.json
│   │       └── context_expected.json
│   │
│   ├── agents/                     # Agent tests
│   │   ├── test_agent_handler.py  # LLM fix generation
│   │   └── fixtures/               # Test fixtures
│   │       ├── context_input.json
│   │       └── fixplan_expected.json
│   │
│   └── github/                     # GitHub integration tests
│       ├── test_pr_generator.py   # PR creation
│       └── fixtures/               # Test fixtures
│           └── fixplan_input.json
│
└── debug/                          # Debug utilities
    ├── debug_pr_generator.py      # Debug PR generator data flow
    ├── debug_git_commit_module.py # Debug git commit operations
    └── outputs/                    # Debug outputs (gitignored)
```

## Running Tests

All tests follow a consistent pattern and can be run in two modes:

### Fixture Mode (Default)
Uses cached test data, no API calls required:
```bash
PYTHONPATH=src python scripts/tests/parsers/test_ruff_parser.py
PYTHONPATH=src python scripts/tests/orchestrator/test_prioritizer.py
PYTHONPATH=src python scripts/tests/agents/test_agent_handler.py
PYTHONPATH=src python scripts/tests/github/test_pr_generator.py
```

### Live Mode
Makes real API calls (requires API keys):
```bash
MAKE_LLM_CALL=true PYTHONPATH=src python scripts/tests/agents/test_agent_handler.py
MAKE_LLM_CALL=true PYTHONPATH=src python scripts/tests/github/test_pr_generator.py
```

## Test Configuration

Tests are configured via environment variables:

### Test Mode
- `MAKE_LLM_CALL`: Set to `true` for live API calls, `false` for fixtures (default: `false`)

### API Keys (required for live mode)
- `OPENAI_API_KEY`: OpenAI API key
- `ANTHROPIC_API_KEY`: Anthropic API key
- `GITHUB_TOKEN`: GitHub personal access token

### Target Repository (for integration tests)
- `TARGET_REPO_ROOT`: Local path to target repository (default: `/home/devel/ardessa-agent`)
- `TARGET_REPO_OWNER`: GitHub repository owner
- `TARGET_REPO_NAME`: GitHub repository name
- `TARGET_REPO_DEFAULT_BRANCH`: Default branch name (default: `main`)

## Fixture Naming Conventions

Fixtures follow the pattern: `{component}_{stage}_{type}.json`

### Examples
- `ruff_input.json` - Raw Ruff JSON input (from CI/CD artifacts)
- `ruff_expected_signals.json` - Expected FixSignal output from parser
- `signals_input.json` - FixSignal list (output from parser, input to orchestrator)
- `groups_expected.json` - Expected SignalGroup output from prioritizer
- `context_expected.json` - Expected context dict from ContextBuilder
- `fixplan_expected.json` - Expected FixPlan output from agent
- `fixplan_input.json` - FixPlan input for PR generator

### Fixture Chaining

Fixtures chain together to enable integration testing:

```
ruff_input.json
  → ruff_expected_signals.json (same as signals_input.json)
  → groups_expected.json
  → context_expected.json (same as context_input.json)
  → fixplan_expected.json (same as fixplan_input.json)
  → PR creation
```

This allows testing the full pipeline or individual components.

## Adding New Parser Tests

To add a test for a new CI/CD tool (e.g., MyPy, Bandit, pytest, coverage):

### Step 1: Create Fixtures

```bash
# Create input fixture from real CI/CD output
cat > scripts/tests/parsers/fixtures/mypy_input.json << 'EOF'
{
  "errors": [
    {"file": "app/main.py", "line": 42, "message": "Missing type annotation"}
  ]
}
EOF

# Create expected output fixture
cat > scripts/tests/parsers/fixtures/mypy_expected_signals.json << 'EOF'
[
  {
    "signal_type": "type_check",
    "severity": "medium",
    "file_path": "app/main.py",
    "message": "Missing type annotation",
    ...
  }
]
EOF
```

### Step 2: Create Test Script

Copy the template:
```bash
cp scripts/tests/parsers/test_ruff_parser.py scripts/tests/parsers/test_mypy_parser.py
```

### Step 3: Customize Test

Edit `scripts/tests/parsers/test_mypy_parser.py`:

```python
from signals.parsers.mypy import parse_mypy_results  # Update import

class MyPyParserTest(BaseTest[dict, list[FixSignal]]):
    """Test MyPy parser."""

    def load_input(self) -> dict:
        return self.load_fixture("mypy_input.json")  # Update fixture name

    def run_component(self, input_data: dict) -> list[FixSignal]:
        return parse_mypy_results(  # Update function call
            input_data,
            repo_root=self.config.target_repo_root,
        )

    # validate_output() stays the same or customize as needed
```

### Step 4: Run the Test

```bash
PYTHONPATH=src python scripts/tests/parsers/test_mypy_parser.py
```

## Test Base Class

All tests inherit from `BaseTest[TInput, TOutput]` which provides:

- **Fixture loading**: `load_fixture(filename)` - Load JSON fixtures
- **Output saving**: `save_output(data, filename)` - Save test outputs
- **Assertions**:
  - `assert_equals(actual, expected, msg)` - Check equality
  - `assert_contains(container, item, msg)` - Check membership
  - `assert_not_empty(value, msg)` - Check non-empty
- **Configuration**: `self.config` - Access to TestConfig
- **Test execution**: `run()` - Execute full test workflow

## Debug Scripts

Debug scripts help trace data flow through individual components:

- **debug_pr_generator.py**: Traces how FixPlan edits are applied to file content
- **debug_git_commit_module.py**: Tests git commit operations step-by-step

Debug outputs are written to `scripts/debug/outputs/` (gitignored).

## Common Patterns

### Loading Test Input

```python
def load_input(self) -> dict:
    """Load test input from fixture."""
    return self.load_fixture("ruff_input.json")
```

### Running Component

```python
def run_component(self, input_data: dict) -> list[FixSignal]:
    """Run the parser."""
    return parse_ruff_lint_results(
        input_data,
        repo_root=self.config.target_repo_root,
    )
```

### Validating Output

```python
def validate_output(self, output: list[FixSignal]) -> TestResult:
    """Validate parsed signals."""
    result = TestResult(success=True, output=output)
    expected = self.load_fixture("ruff_expected_signals.json")

    # Check count
    if self.assert_equals(len(output), len(expected), "Signal count"):
        result.assertions_passed += 1
    else:
        result.assertions_failed += 1
        result.success = False

    return result
```

## Troubleshooting

### Import Errors

Make sure to run tests with `PYTHONPATH=src`:
```bash
PYTHONPATH=src python scripts/tests/parsers/test_ruff_parser.py
```

### Fixture Not Found

Ensure fixtures are in the correct location:
```
scripts/tests/parsers/fixtures/ruff_input.json
scripts/tests/parsers/fixtures/ruff_expected_signals.json
```

### API Key Errors

For live mode, set required API keys:
```bash
export OPENAI_API_KEY="your-key-here"
MAKE_LLM_CALL=true PYTHONPATH=src python scripts/tests/agents/test_agent_handler.py
```

### Test Failures

Check the output file in `scripts/debug/outputs/` to inspect actual vs expected results:
```bash
cat scripts/debug/outputs/output.json
```

## Future Enhancements

Planned additions to the test suite:

- `test_mypy_parser.py` - MyPy type checker parser
- `test_bandit_parser.py` - Bandit security scanner parser
- `test_pytest_parser.py` - Pytest test results parser
- `test_coverage_parser.py` - Coverage.py results parser
- `tests/integration/test_full_pipeline.py` - End-to-end integration test

The infrastructure is in place to easily add these tests following the patterns above.

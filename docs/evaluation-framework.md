# CICD AI Assistant Evaluation Framework

This document describes how to use the evaluation framework to measure the performance of the CICD AI Assistant.

## Overview

The evaluation framework allows you to:
1. Define test cases from frozen CICD artifacts
2. Run the assistant against each test case
3. Create PRs to a test repository
4. Evaluate fixes via GitHub Copilot code review
5. Run regression tests to verify no breakage
6. Generate metrics and reports

## Quick Start

### 1. Fork Your Target Repository

Create a fork of `ardessa-repo` called `ardessa-repo-test` (or similar) that will be used for evaluation PRs.

### 2. Freeze CICD Artifacts

Copy the CICD tool outputs from a recent run to the artifacts directory:

```bash
mkdir -p evaluation/artifacts
cp /path/to/ruff-lint-results.json evaluation/artifacts/
cp /path/to/mypy-results.json evaluation/artifacts/
cp /path/to/bandit-results.json evaluation/artifacts/
```

### 3. Generate Test Cases

Generate test cases from your artifacts:

```bash
# Generate test cases from a Ruff artifact
python scripts/evaluate.py --generate-cases evaluation/artifacts/ruff-lint-results.json --generate-tool ruff

# Generate test cases from a MyPy artifact
python scripts/evaluate.py --generate-cases evaluation/artifacts/mypy-results.json --generate-tool mypy
```

This creates YAML files in `evaluation/test_cases/`.

### 4. Configure Environment

Set up the required environment variables:

```bash
# Required
export GITHUB_TOKEN="your-github-pat"
export EVAL_REPO_OWNER="your-org"
export EVAL_REPO_NAME="ardessa-repo-test"

# Optional
export EVAL_REPO_BRANCH="main"           # Base branch for PRs
export EVAL_REPO_ROOT="/path/to/clone"   # For regression tests
export LLM_PROVIDER="openai"             # or "anthropic"
export OPENAI_API_KEY="your-key"         # If using OpenAI
```

### 5. Run Evaluation

```bash
# Full evaluation
python scripts/evaluate.py

# Dry run (no PRs created)
python scripts/evaluate.py --dry-run

# Skip reviews for faster iteration
python scripts/evaluate.py --skip-review --skip-regression

# Run only Ruff tests
python scripts/evaluate.py --tool ruff

# Verbose output
python scripts/evaluate.py -v
```

## Directory Structure

```
evaluation/
├── artifacts/           # Frozen CICD tool outputs
│   ├── ruff-lint-results.json
│   ├── mypy-results.json
│   └── bandit-results.json
├── test_cases/          # Test case definitions (YAML)
│   ├── sample_cases.yaml
│   └── ruff_cases.yaml
└── results/             # Evaluation outputs
    ├── run_20240115_143022.json
    └── report_20240115_143022.md

src/evaluation/          # Framework source code
├── __init__.py
├── harness.py           # Main orchestrator
├── test_case.py         # Test case model
├── reviewer.py          # GitHub Copilot integration
├── regression.py        # Regression test runner
├── metrics.py           # Metrics calculation
└── report.py            # Report generation
```

## Test Case Format

Test cases are defined in YAML:

```yaml
test_cases:
  - id: ruff-F401-1                    # Unique identifier
    tool: ruff                          # ruff, mypy, bandit
    signal_type: lint                   # lint, type_check, security, format
    artifact_path: artifacts/ruff.json  # Path to artifact
    error_code: F401                    # Specific error code
    file_path: app/example.py           # Target file
    line_number: 42                     # Line number (optional)
    message: "unused import"            # Error message
    description: "Remove unused import"
    expected_outcome: fix               # fix, partial_fix, skip
    tags:                               # Optional tags for filtering
      - unused-import
      - safe-fix
```

## Metrics

The framework tracks these metrics:

| Metric | Description |
|--------|-------------|
| `fix_success_rate` | % of test cases that produced successful fixes |
| `pr_creation_rate` | % of test cases that created PRs |
| `review_approval_rate` | % of PRs approved by Copilot |
| `regression_pass_rate` | % of test cases where regression tests passed |
| `avg_confidence` | Average confidence score from the LLM |

Metrics are broken down by:
- Tool (ruff, mypy, bandit)
- Signal type (lint, type_check, security)
- Error code (F401, arg-type, etc.)

## Reports

The framework generates two report formats:

### JSON Report

Machine-readable format for further analysis:

```json
{
  "run_id": "20240115_143022",
  "metrics": {
    "summary": {
      "total_cases": 50,
      "fix_success_rate": 72.0,
      "review_approval_rate": 85.0
    },
    "by_tool": {
      "ruff": 30,
      "mypy": 20
    }
  },
  "results": [...]
}
```

### Markdown Report

Human-readable format with tables and summaries:

```markdown
# Evaluation Report
## Summary Metrics
| Metric | Value |
|--------|-------|
| Total Test Cases | 50 |
| Fix Success Rate | 72.0% |
...
```

## GitHub Copilot Review

The framework requests code reviews from GitHub Copilot:

1. Creates a PR from the fix
2. Requests review from `@copilot`
3. Polls for review completion (timeout: 5 minutes)
4. Extracts verdict (approved/changes_requested/commented)

Requirements:
- GitHub Copilot Enterprise or Copilot for Business
- Code review feature enabled for the repository

## Regression Testing

Regression tests verify fixes don't break existing functionality:

1. Fetches the PR branch locally
2. Runs pytest (configurable)
3. Parses JUnit XML results
4. Records pass/fail counts

Configuration:

```bash
export EVAL_REPO_ROOT="/path/to/local/clone"
```

## Comparing Runs

Compare two evaluation runs to measure improvement:

```python
from evaluation.report import generate_comparison_report
from evaluation.harness import EvaluationHarness

# Load previous run results
# ...

generate_comparison_report(run1, run2, "evaluation/results")
```

## Programmatic Usage

```python
from evaluation import EvaluationHarness, EvaluationConfig

config = EvaluationConfig(
    test_repo_owner="my-org",
    test_repo_name="ardessa-test",
    llm_provider="openai",
    skip_review=True,  # Faster iteration
)

harness = EvaluationHarness(config)

# Progress callback
def on_progress(result):
    print(f"Completed: {result.test_case.id}")

harness.set_progress_callback(on_progress)

# Run evaluation
run = harness.run_evaluation(filter_tool="ruff")

# Access results
print(f"Success rate: {run.metrics.fix_success_rate}%")
for result in run.results:
    if not result.is_successful:
        print(f"Failed: {result.test_case.id} - {result.error_message}")
```

## Best Practices

1. **Start with dry runs**: Use `--dry-run` to verify test cases without creating PRs
2. **Filter by tool**: Test one tool at a time with `--tool ruff`
3. **Skip reviews initially**: Use `--skip-review` for faster iteration while debugging
4. **Use tags**: Tag test cases for fine-grained filtering
5. **Compare runs**: Generate comparison reports to track improvement over time

## Troubleshooting

### "GITHUB_TOKEN is required"
Set the `GITHUB_TOKEN` environment variable with a PAT that has repo access.

### "Repository path does not exist"
For regression tests, set `EVAL_REPO_ROOT` to a local clone of the test repository.

### "Review timed out"
Copilot reviews can take time. Increase `REVIEW_TIMEOUT` in the config or skip reviews with `--skip-review`.

### Test case not found
Ensure the artifact path is correct and the error code matches exactly.

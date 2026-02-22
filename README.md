# cicd-ai-assistant

An AI-powered CI/CD assistant that ingests pipeline signals from static analysis tools and automatically generates pull requests with code fixes. Built as a research prototype for a thesis investigating LLM-assisted automated code correction.

## What It Does

The assistant accepts output from common Python quality tools (ruff, mypy, pydocstyle), parses the violations into a normalised signal format, prioritises them by severity, and generates fixes — either by direct application (for formatting) or via an LLM (for lint, type, and docstring issues). Fixed code is committed to a new branch and a pull request is opened via the GitHub API.

## Pipeline

```
Tool Output → Parse → Prioritise → Plan Fix → Open PR
```

1. **Parsing** — raw tool output is converted into structured `FixSignal` objects
2. **Prioritisation** — signals are grouped and ordered: TYPE_CHECK → LINT → DOCSTRING → FORMAT
3. **Fix Planning** — format fixes are applied directly; all others are sent to an LLM with tool-specific prompts
4. **PR Generation** — edits are committed to a branch and a pull request is created

## Supported Tools

- `ruff` — lint violations and formatting diffs
- `mypy` — type check errors
- `pydocstyle` — missing docstring violations

## Requirements

- Python 3.11+
- `uv` (recommended) or `pip`
- An Anthropic API key (for LLM-based fixes)
- A GitHub personal access token (for PR creation)

## Setup

```bash
# Install dependencies
uv sync

# Copy and fill in environment variables
cp .env.example .env
```

### Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key for LLM fix generation |
| `GITHUB_TOKEN` | GitHub personal access token |
| `TARGET_REPO_OWNER` | Owner of the repository to open PRs against |
| `TARGET_REPO_NAME` | Name of the repository to open PRs against |
| `AUTO_APPLY_FORMAT_FIXES` | Skip LLM for format fixes — `true` by default |

## Running

```bash
python src/main.py
```

## Repository Structure

See `artifact-repo-summary.md` for a full breakdown of the repository contents.

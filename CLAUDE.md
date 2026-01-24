# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered CI/CD assistant that ingests pipeline signals (lint, type-check, format, security) and generates pull requests with fixes. Uses LLMs with tool-specific prompts to generate code corrections.

## Development Status

**Core pipeline implemented.** Working components:
- Signal parsers for ruff (lint/format) and mypy (type-check)
- Prioritizer with severity-based ordering
- Fix planner with direct-apply (format) and LLM paths
- Tool-specific LLM prompts (mypy, ruff, bandit)
- PR generator with GitHub API integration

**Not yet implemented:** bandit parser, pytest/coverage parsers, validation loops

## Architecture

See `docs/current-application-setup.md` for detailed pipeline flow.

### Core Pipeline
1. **Parsing** → `src/signals/parsers/` - Convert tool output to FixSignal objects
2. **Prioritization** → `src/orchestrator/prioritizer.py` - Group and order by severity
3. **Fix Planning** → `src/orchestrator/fix_planner.py` - Generate fixes (LLM or direct)
4. **PR Generation** → `src/github/pr_generator.py` - Apply edits and create PRs


## Key Data Types

```python
FixSignal:
  signal_type: LINT | FORMAT | TYPE_CHECK | SECURITY
  severity: LOW | MEDIUM | HIGH | CRITICAL
  file_path: str
  span: Span(start, end)
  rule_code: str
  message: str
  fix: Fix | None  # Contains TextEdits if auto-fixable
```

## LLM Integration

Tool-specific prompts in `src/agents/tool_prompts.py`:
- **mypy**: Type annotation fixes, validation preservation, type guards
- **ruff**: Lint fixes, unused code removal, style improvements
- **bandit**: Security fixes with high caution (planned)

The agent returns fixed code snippets that are parsed and applied to files.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `AUTO_APPLY_FORMAT_FIXES` | Bypass LLM for format fixes (default: true) |
| `GITHUB_TOKEN` | GitHub PAT for PR creation |
| `TARGET_REPO_OWNER` | Target repository owner |
| `TARGET_REPO_NAME` | Target repository name |
| `ANTHROPIC_API_KEY` | For LLM provider |

## Related Documentation

- `docs/current-application-setup.md` - Pipeline architecture and data flow
- `docs/current-directory-setup.md` - Current file structure
- `docs/TOOL_SPECIFIC_PROMPTS.md` - LLM prompt documentation
- `docs/architectural-design.md` - Original design spec

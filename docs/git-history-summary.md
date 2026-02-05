# Git History Summary

Chronological summary of project development for the CI/CD AI Assistant.

---

## 2025-12-09 — `9aeb54d` — Initial commit

- Repository initialised with `.gitignore` and `README.md`.

---

## 2025-12-15 — `1a7f4ef`, `40fa893` — Architecture and planning documentation

- Created the initial architectural design document (`docs/architectural-design.md`) outlining the full pipeline vision: signal ingestion, prioritisation, agent-based fix generation, and PR creation.
- Added a directory plan (`docs/directory-plan.md`) mapping out the intended project structure.
- Initialised the `src/` package with `__init__.py`.
- Revised and condensed the architectural design doc in a follow-up pass.

---

## 2025-12-16 — `f2dcccc` — Sample CI/CD artifact ingestion

- Added sample output files from real CI/CD tool runs to `sample-cicd-artifacts/`:
  - `ruff-lint-results.json` — ruff lint output (~20k lines)
  - `ruff-format-output.txt` — ruff format output (~69k lines)
  - `ruff-format-results.json`
  - `mypy-results.json` — mypy type-check output
  - `bandit-results.json` — bandit security scan output
  - `pytest-results.xml` and `pytest-coverage.json`/`.xml`
- Updated `.gitignore` and design/plan docs to reflect the new artefacts.

---

## 2025-12-22 — `6d1501e` — Signals library foundation

- Created the core `src/signals/` package — the data model layer for the entire pipeline.
- Defined `FixSignal` dataclass and supporting types: `SignalType` (LINT, TYPE_CHECK, SECURITY), `Severity` (CRITICAL/HIGH/MEDIUM/LOW), `FixApplicability`, `Position`, `Span`, `TextEdit`, and `Fix`.
- Implemented `severity_for_ruff()` in `src/signals/policy/severity.py` — a rule-code-to-severity mapper for ruff lint rules.
- Established the pattern of frozen dataclasses used throughout the project.

---

## 2025-12-24 — `5344980` — Ruff lint parser and path policy

- Built `src/signals/parsers/ruff.py` — the first signal parser, converting ruff JSON lint output into `FixSignal` objects.
  - Handles rule code extraction, span mapping, fix/edit parsing, and docs URL construction.
  - Converts ruff's native edit format (0-indexed offsets) into the project's `TextEdit` model.
- Added `src/signals/policy/path.py` with `to_repo_relative()` for normalising file paths against the repository root.

---

## 2025-12-26 — `3108471`, `cc6d9ea` — Orchestrator and prioritiser

- Set up `pyproject.toml` with project dependencies and `uv.lock`.
- Created `src/orchestrator/prioritizer.py` — groups `FixSignal` objects into `SignalGroup` batches for agent processing.
  - Groups by tool (tool-homogeneous batches, max 3 signals per group).
  - Includes severity-based ordering and a pluggable tool-resolver heuristic.
  - Defined `SignalGroup` dataclass as the interface between parsing and fix generation.
- Added `scripts/test_parsing.py` for end-to-end manual testing of the parsing pipeline.
- Fixed module import issues by adding `__init__.py` files to `parsers/` and `policy/` subpackages.

---

## 2026-01-03 — `ddfee4a` — Context builder

- Created `src/orchestrator/context_builder.py` — assembles file context for LLM prompts.
  - Reads source files and builds windowed code snippets around each signal's span (configurable ± N lines).
  - Extracts import blocks from the top of files.
  - Extracts the enclosing function/method block using an indentation-based heuristic.
  - Attaches fix metadata and edit details when available.
  - Produces a structured dict per `SignalGroup` ready for LLM consumption.
- Updated directory plan docs.

---

## 2026-01-04 — `16903f1`, `2d76808`, `4f4bb17` — Agent handler and LLM provider

- Created `src/agents/llm_provider.py` — an abstraction layer supporting multiple LLM backends:
  - `OpenAIProvider` and `AnthropicProvider` implementations.
  - Standardised `LLMResponse` and `LLMError` types.
  - Retry logic with exponential backoff for transient API failures.
  - Environment-variable-driven configuration (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, model selection).
  - Factory function `get_provider()` for provider instantiation.
- Created `src/agents/agent_handler.py` — the core fix-generation module:
  - Takes context from `ContextBuilder.build_group_context()` and sends it to an LLM.
  - Parses structured JSON responses into `FixPlan` objects containing `FileEdit` and `CodeEdit` items.
  - Defined `FixPlan`, `FileEdit`, `CodeEdit`, `EditType`, `Position`, `Span` models for edit representation.
  - Includes response validation and error handling.
- Added `scripts/test_agent_handler.py` and sample context/output JSON files for manual testing.

---

## 2026-01-05 — `eb4ffea` — LLM provider improvements

- Refactored `llm_provider.py` for improved OpenAI API usage and response handling.

---

## 2026-01-06 to 2026-01-07 — `cb6d02e`, `da5a54d`, `bc0ab56`, `330a6f7` — PR generator module

- Created `src/github/pr_generator.py` — the final pipeline stage, turning `FixPlan` objects into GitHub pull requests:
  - Fetches file content from GitHub API, applies code edits, and commits changes to a new branch.
  - Handles edit application with correct span-based text replacement.
  - Creates PRs via the GitHub API with configurable labels, draft mode, and branch naming.
  - Defined `PRResult` dataclass for operation outcomes.
  - Configuration driven by environment variables (`GITHUB_TOKEN`, `TARGET_REPO_OWNER`, `TARGET_REPO_NAME`, etc.).
- Added debug scripts and output files for tracing the data flow through edit application (indexing/off-by-one investigation).

---

## 2026-01-08 to 2026-01-10 — `ea01706`, `3fef7da`, `d3927bc`, `3e028d0`, `9c5897a` — PR generator refinement

- Fixed a bug in `pr_generator.py` where a prefixed slash in the branch name caused commit failures.
- Added `merge_file_edits()` function to combine multiple `FileEdit` objects targeting the same file into a single edit, preventing conflicting commits.
- Improved commit message generation to list all fix descriptions with line numbers when multiple edits are merged for one file.
- Added and iterated on test/debug scripts for the git commit module.
- Cleaned up debug artefacts from the repository.

---

## 2026-01-11 — `8f0573f`, `fafc938`, `265e410`, `019d1b7` — PR generator merge (PR #3)

- Removed remaining debug steps and output files from `pr_generator`.
- Merged PR #3 (`claude/debug-pr-generator`) into main, completing the PR generator feature.

---

## 2026-01-15 — `eb5ef3b` — Ruff format parser

- Built `src/signals/parsers/ruff.py` (format parsing additions) — a second parsing pathway for ruff's format/diff output.
  - Parses unified-diff-style format output into `FixSignal` objects with `FORMAT` signal type.
  - Extracts per-file diffs, maps hunks to `TextEdit` objects with correct spans.
  - Signals are marked as auto-fixable (`FixApplicability.SAFE`) since format changes are deterministic.
- Added `FORMAT` to the `SignalType` enum in `models.py`.
- Added sample shortened format output and a test script (`scripts/test_ruff_format.py`).

---

## 2026-01-16 — `6ea2795`, `cd42733` — Fix planner and updated documentation

- Created `src/orchestrator/fix_planner.py` — the decision layer between direct-apply and LLM-assisted fixes:
  - Direct-apply path for `FORMAT` signals: converts `FixSignal.fix` edits directly into `FixPlan` objects without LLM involvement (controlled by `AUTO_APPLY_FORMAT_FIXES` env var).
  - LLM-assisted path for lint, type-check, and security signals: uses `ContextBuilder` + `AgentHandler` to generate fixes.
  - Returns `FixPlanResult` with success/failure status, the generated plan, and metadata about the path taken.
- Enhanced the prioritiser to support the new `FORMAT` signal type and updated grouping logic.
- Added `docs/current-application-setup.md` documenting the full pipeline flow with data types at each stage.
- Added `docs/current-directory-setup.md` documenting the file/module structure.

---

## 2026-01-17 to 2026-01-19 — `2ba7063`, `ca8f7c8`, `f68e3c6` — Mypy parser

- Created `src/signals/parsers/mypy.py` — parser for mypy JSON output:
  - Converts mypy diagnostic entries into `FixSignal` objects with `TYPE_CHECK` signal type.
  - Maps mypy severity levels to the project's `Severity` enum.
  - Handles mypy error codes and message extraction.
- Added `severity_for_mypy()` to `src/signals/policy/severity.py` with mypy-specific severity mappings.
- Fixed a bug in `pr_generator.py` where a leading slash in branch names caused GitHub API commit failures.
- Added sample mypy result files and a test script (`scripts/test_mypy.py`).

---

## 2026-01-19 — `46b24c5`, `1d17fea` — Tool-specific LLM prompts

- Created `src/agents/tool_prompts.py` — centralised, tool-specific system prompts for LLM fix generation:
  - `BASE_SYSTEM_PROMPT`: core instructions for JSON-structured fix output, edit types, span conventions.
  - `MYPY_GUIDANCE`: type annotation strategies, validation preservation, type guard patterns, stub handling.
  - `RUFF_GUIDANCE`: lint fix patterns, unused import removal, style conventions, common rule-code advice.
  - `BANDIT_GUIDANCE`: security fix patterns with emphasis on caution and not introducing new vulnerabilities.
  - `get_system_prompt(tool_id)` function to compose base + tool-specific prompts dynamically.
- Refactored `agent_handler.py` to use the new prompt system instead of inline prompt strings.
- Updated `context_builder.py` to pass tool metadata through to prompts.
- Added `docs/TOOL_SPECIFIC_PROMPTS.md` documenting prompt architecture and `scripts/verify_tool_prompts.py` for validation.

---

## 2026-01-22 — `bac0704`..`942ae87` (feature branch), merged in PR #7 — LLM response refactor and prompt improvements

- Refactored the LLM response format: agent now returns altered code strings (full replacement snippets) rather than parsed JSON with positional edit data.
  - Simplified the edit application logic — the agent provides the corrected code directly instead of precise span-based edits.
  - Updated `agent_handler.py` with new response parsing for the string-based format.
  - Updated `tool_prompts.py` to instruct the LLM to return code blocks rather than JSON edit plans.
- Enhanced `context_builder.py` with additional context-building methods to support the new prompt structure.
- Added new methods to `fix_planner.py` for handling the refactored response format.
- Fixed prompt and LLM return parsing issues discovered during testing.
- Switched default LLM provider to Anthropic.

---

## 2026-01-23 — `73c17c2` — Documentation cleanup

- Removed outdated planning docs (`architectural-design.md`, `directory-plan.md`) that were superseded by current application docs.
- Updated `current-application-setup.md` and `current-directory-setup.md` to reflect the current state of the codebase.

---

## 2026-01-24 — `4093493`, `e82a593` — CLAUDE.md and architecture diagram

- Added `CLAUDE.md` to the repository with project overview, architecture summary, key data types, LLM integration notes, and environment variable documentation.
- Created `docs/module-architecture-diagram.md` with a comprehensive Mermaid diagram documenting:
  - All 5 primary modules and their connections.
  - Complete data structure interfaces (`FixSignal`, `SignalGroup`, `FixPlan`, `PRResult`).
  - Two processing paths (direct conversion vs LLM-assisted).
  - Data flow from CI/CD tool outputs to PR creation.
  - Entry point pseudocode for future `main()` implementation.

---

## 2026-01-25 — `e7e2c0f` — Signal-specific context and edit windows

- Created `src/orchestrator/signal_requirements.py` — configuration for signal-specific context windows:
  - Defines `EditWindowSpec` with window types: `lines`, `function`, `imports`, `try_except`.
  - `get_edit_window_spec()` maps rule codes to appropriate window strategies (e.g. `F401` uses import-block windows, `E722` uses try/except-block windows).
  - Allows each signal type to get a tailored context window size and type for LLM prompts.
- Significantly expanded `context_builder.py` (~540 lines) to use the new window specs:
  - Builds separate context windows and edit windows per signal.
  - Context windows provide surrounding code for understanding; edit windows provide the precise region the LLM should modify.
- Updated `agent_handler.py` and `tool_prompts.py` to consume the new tailored context/edit structure.
- Added `docs/SIGNAL_CONTEXT_REQUIREMENTS.md` documenting the context and edit window design.

---

## 2026-01-27 — `de7b850` — Pydocstyle integration

- Created `src/signals/parsers/pydocstyle.py` — parser for pydocstyle text output:
  - Parses pydocstyle's `{file}:{line} at {location}: {code}: {message}` format.
  - Filters to only D101 (missing class docstring), D102 (missing method docstring), D103 (missing function docstring).
  - Converts matches into `FixSignal` objects with `DOCSTRING` signal type — no auto-fix available, requires LLM generation.
- Added `DOCSTRING` to `SignalType` enum and `severity_for_pydocstyle()` to severity policy.
- Extended all pipeline modules to handle the new signal type:
  - `tool_prompts.py`: added pydocstyle-specific LLM guidance for docstring generation.
  - `context_builder.py`: added pydocstyle context building with function-level windowing.
  - `signal_requirements.py`: added pydocstyle edit window specs (function-scoped).
  - `prioritizer.py`: updated tool resolver for pydocstyle signals.
  - `agent_handler.py`: added pydocstyle response handling.
- Added sample pydocstyle output files and `scripts/test_pydocstyle.py`.
- Updated application setup and directory docs.

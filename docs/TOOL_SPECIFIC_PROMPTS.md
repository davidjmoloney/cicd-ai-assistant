# Tool-Specific Prompting System

## Overview

The AI fix generation agent now uses **tool-specific prompts** that provide specialized guidance based on the type of CI/CD signal being fixed (MyPy, Ruff, Bandit, etc.).

This dramatically improves fix quality by giving the LLM context-appropriate instructions for each tool's specific concerns.

## Architecture

### Files

```
src/agents/
├── tool_prompts.py       # NEW: All prompts centralized here
├── agent_handler.py      # UPDATED: Uses tool-specific prompts
└── llm_provider.py       # Unchanged

scripts/
└── verify_tool_prompts.py  # NEW: Verification/testing script
```

### How It Works

```python
# 1. Context contains tool_id
context = {
    "group": {
        "tool_id": "mypy",  # <-- Extracted from signals
        "signal_type": "type_check",
        ...
    },
    "signals": [...]
}

# 2. AgentHandler extracts tool_id
tool_id = context.get("group", {}).get("tool_id")

# 3. Gets appropriate prompt
system_prompt = get_system_prompt(tool_id)  # Returns MyPy-specific guidance

# 4. Sends to LLM with tool-specific instructions
response = llm.generate(system_prompt=system_prompt, user_prompt=user_prompt)
```

## Tool-Specific Prompts

### MyPy (Type Checking)

**Focus**: Preserve validation logic while fixing type errors

**Key Guidance**:
- ⚠️ **NEVER bypass validation** by adding ` or ''` to checked values
- Recognize validation patterns (code that raises errors for None/missing)
- Prefer type annotations and type guards over default values
- Security-critical code (JWT, auth) must keep validation intact

**Example Improvements**:
```python
# BEFORE (generic prompt):
# LLM would add: jwks_url = get_url() or ""  # ❌ Bypasses validation!

# AFTER (MyPy-specific prompt):
# LLM adds assertion: assert jwks_url is not None  # ✅ Preserves validation
```

### Ruff (Linting)

**Focus**: Code quality and style improvements

**Key Guidance**:
- Low risk - these are style issues, not bugs
- Remove unused code (but check for side effects)
- Follow Python idioms and PEP 8
- Don't break working code to satisfy complexity metrics

**Example Improvements**:
```python
# BEFORE: Might suggest complex refactoring
# AFTER: Suggests simple fixes like renaming or removing unused imports
```

### Bandit (Security)

**Focus**: CRITICAL security vulnerabilities

**Key Guidance**:
- ⚠️ **EXTREME CAUTION** - security fixes can have severe consequences
- NEVER weaken security to fix warnings
- NEVER add `# nosec` without understanding
- When unsure, set confidence < 0.5 for human review
- Use secure alternatives (sha256 vs md5, parameterized queries)

**Example Improvements**:
```python
# BEFORE (generic prompt):
# LLM might disable security: verify=False  # ❌

# AFTER (Bandit-specific prompt):
# LLM suggests secure alternative or flags for review  # ✅
```

## Prompt Structure

### Base Prompt (All Tools)
- JSON response format
- Span syntax (row/column rules)
- Edit types (replace/insert/delete)
- General guidelines

### Tool-Specific Additions
- Specialized strategies for that tool type
- Risk level warnings
- Common patterns and anti-patterns
- Confidence guidelines
- Examples of good vs bad fixes

## Usage

### Normal Usage (Automatic)

The system automatically selects the right prompt based on signals:

```python
from orchestrator.fix_planner import FixPlanner

planner = FixPlanner(repo_root="/path/to/repo")
result = planner.create_fix_plan(signal_group)  # Tool-specific prompt used automatically
```

### Manual Prompt Selection (Testing/Debug)

```python
from agents.tool_prompts import get_system_prompt

# Get specific prompt
mypy_prompt = get_system_prompt("mypy")
bandit_prompt = get_system_prompt("bandit")
base_prompt = get_system_prompt(None)  # Fallback to base

# List supported tools
from agents.tool_prompts import list_supported_tools
tools = list_supported_tools()  # ['mypy', 'ruff', 'ruff-lint', 'ruff-format', 'bandit']
```

### Override (Custom Prompts)

```python
from agents.agent_handler import AgentHandler

# Use custom prompt for all tools
handler = AgentHandler(system_prompt="My custom instructions...")
result = handler.generate_fix_plan(context)  # Uses custom prompt
```

## Verification

Run the verification script to test the prompting system:

```bash
python3 scripts/verify_tool_prompts.py
```

This will:
- List all supported tools
- Show prompt lengths (base vs tool-specific)
- Verify critical keywords are present
- Display preview of each tool's guidance

## Adding New Tools

To add a new tool (e.g., `pytest`, `black`, `pylint`):

1. **Add guidance in `src/agents/tool_prompts.py`**:
   ```python
   PYTEST_GUIDANCE = """
   ## Pytest Test Error Fixing - Specialized Guidance

   Focus: Fix failing tests
   Risk Level: MEDIUM
   ...
   """

   TOOL_SPECIFIC_PROMPTS = {
       ...
       "pytest": PYTEST_GUIDANCE,
   }
   ```

2. **Test it**:
   ```bash
   python3 scripts/verify_tool_prompts.py
   ```

3. **Use it**:
   ```python
   # Automatic - just parse signals with tool_id="pytest"
   signals = parse_pytest_results(output)  # Must set tool_id="pytest"
   ```

That's it! No changes needed to `agent_handler.py` or other code.

## Benefits

### Before (One-Size-Fits-All)

```
❌ MyPy fixes bypassed validation logic
❌ Security fixes weakened protections
❌ LLM treated all errors the same
❌ No understanding of tool-specific risks
```

### After (Tool-Specific)

```
✅ MyPy fixes preserve validation
✅ Security fixes maintain or strengthen protections
✅ LLM understands tool context
✅ Risk-appropriate confidence levels
✅ Better fix quality overall
```

## Maintenance

### Where to Edit

- **Prompts**: `src/agents/tool_prompts.py` - All prompts in one place
- **Integration**: `src/agents/agent_handler.py` - Prompt selection logic
- **Testing**: `scripts/verify_tool_prompts.py` - Verification

### Best Practices

1. **Keep prompts focused** - Each tool gets guidance for its specific concerns
2. **Use examples** - Show good vs bad fixes
3. **Emphasize risks** - Security > type safety > style
4. **Test changes** - Run verify script after editing
5. **Version control** - Document why changes were made

## Next Steps

1. ✅ **Implemented**: Tool-specific prompts
2. 🔄 **Current**: Test with MyPy (regenerate fix plans)
3. ⏭️ **Next**: Enhance context (add function signatures, type hints)
4. ⏭️ **Future**: Try Claude Sonnet 3.5 for even better reasoning

## Expected Improvements

Based on the code review of the previous fix plan:

### Should Now Be Fixed
- ✅ MyPy validation bypass (clerk_tokens.py) - Prompt now emphasizes preservation
- ✅ Nonsensical defaults (config.py returning '0' as URL) - Better guidance on semantics
- ✅ Zero-width REPLACE spans - Still flagged by validation but LLM should do better

### Still Needs Work
- ⚠️ Complex test code issues (json_to_excel.py) - May need better context
- ⚠️ Business logic decisions - LLM can't know domain rules without context

## Metrics to Track

When regenerating fix plans, compare:

1. **Validation preservation** - Count fixes that bypass vs preserve validation
2. **Confidence scores** - Should be lower for complex/security code
3. **Zero-width spans** - Should decrease with better guidance
4. **Semantic correctness** - Fewer nonsensical defaults (like '0' for URLs)
5. **Overall acceptance rate** - More fixes safe to merge

---

**Status**: ✅ Fully Implemented and Verified

**Last Updated**: 2026-01-19

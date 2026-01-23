# Vulture Integration Plan

## Tool Overview

**Vulture** is a dead code detection tool for Python. It finds unused code including:
- Unused functions and methods
- Unused classes
- Unused variables
- Unused imports (beyond what ruff catches)
- Unreachable code

### Why It's a Good Fit

1. **Extremely localized fixes** - Dead code removal is the simplest possible fix: delete the unused code
2. **Novel value** - Ruff catches unused imports, but vulture goes deeper into unused functions/classes
3. **Low false-positive rate** - Confidence scoring allows tuning sensitivity
4. **Clean JSON output** - Easy to parse into signal objects
5. **Zero behavioral risk** - Removing truly dead code cannot break functionality

---

## GitHub Actions Setup

```yaml
- name: Run Vulture
  run: |
    pip install vulture
    vulture app/ --min-confidence 80 --make-whitelist > vulture-whitelist.txt || true
    vulture app/ --min-confidence 80 --exclude "*/tests/*" -o json > vulture-output.json || true
```

### Arguments Explained

| Argument | Value | Rationale |
|----------|-------|-----------|
| `--min-confidence` | `80` | Only report findings vulture is 80%+ confident about. Lower values catch more but increase false positives. Start conservative. |
| `--exclude` | `*/tests/*` | Test files often have intentionally "unused" fixtures, parametrize values, etc. Exclude to reduce noise. |
| `-o json` | - | JSON output for parsing into signal objects |
| `--make-whitelist` | - | Generates a whitelist file for known false positives (run once during setup) |

### Alternative: Stricter Settings

```yaml
vulture app/ --min-confidence 90 --exclude "*/tests/*,*/migrations/*" -o json
```

Use `90` confidence for even fewer false positives during initial rollout.

---

## Output Format

Vulture JSON output structure:
```json
[
  {
    "filename": "app/utils/helpers.py",
    "lineno": 42,
    "name": "unused_function",
    "type": "function",
    "confidence": 100,
    "message": "unused function 'unused_function'"
  }
]
```

### Mapping to Signal Object

```python
signal = Signal(
    tool="vulture",
    file_path=item["filename"],
    line_number=item["lineno"],
    severity="warning",  # Dead code is not critical
    message=item["message"],
    code_type=item["type"],  # function, variable, class, etc.
    confidence=item["confidence"]
)
```

---

## Implementation Steps

### 1. Add Vulture Parser Module

Create `src/parsers/vulture_parser.py`:
- Parse JSON output from vulture
- Convert to Signal objects
- Filter by confidence threshold (configurable)

### 2. Add Vulture Fix Generator

The fix for dead code is straightforward:
- For unused functions/classes: Delete the entire definition
- For unused variables: Delete the assignment line
- For unused imports: Delete the import line (though ruff handles this)

**Key consideration:** When deleting a function, ensure you capture the full function body including decorators.

### 3. Create Whitelist Management

Vulture supports whitelisting known false positives:
```python
# vulture_whitelist.py
unused_function  # Used via getattr
MyClass.dynamic_method  # Called dynamically
```

The assistant should:
- Detect likely false positives (dynamic access patterns)
- Suggest whitelist additions when appropriate
- Not repeatedly flag whitelisted items

### 4. Context Gathering Strategy

For dead code removal, minimal context is needed:
- Read the file containing the dead code
- Identify the full extent of the dead code (function boundaries, decorators)
- Verify no dynamic references exist (search for string references to the name)

### 5. Integration Checklist

- [ ] Create `vulture_parser.py` in parsers module
- [ ] Add vulture to `requirements-dev.txt` or tool dependencies
- [ ] Create fix generation logic for dead code removal
- [ ] Add vulture step to GitHub Actions workflow
- [ ] Create initial whitelist for known false positives
- [ ] Add configuration options for confidence threshold
- [ ] Write tests for parser and fix generation

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| False positive (code used dynamically) | Medium | Use high confidence threshold, search for string references |
| Removing code used in tests only | Low | Separate test analysis, or flag for review |
| Breaking re-exports | Low | Check `__all__` exports before removal |

---

## Example Fix Generation

**Input Signal:**
```json
{
  "filename": "app/utils/helpers.py",
  "lineno": 42,
  "name": "calculate_legacy_total",
  "type": "function",
  "confidence": 100
}
```

**Generated Fix:**
```python
# Delete lines 41-55 (function definition with decorator)
# Before:
@deprecated
def calculate_legacy_total(items):
    """Legacy calculation method."""
    total = 0
    for item in items:
        total += item.price
    return total

# After:
# (lines removed)
```

---

## Estimated Implementation Effort

- Parser module: ~2 hours
- Fix generator: ~3 hours
- Testing & whitelist setup: ~2 hours
- **Total: ~7 hours**

**Ease of Implementation: 85/100**

# Pydocstyle Integration Plan

## Tool Overview

**Pydocstyle** is a static analysis tool for checking compliance with Python docstring conventions (PEP 257). It validates:
- Docstring presence (functions, classes, modules)
- Docstring formatting (indentation, quotes, blank lines)
- Docstring content structure (summary line, descriptions)

### Why It's a Good Fit

1. **Perfect for AI generation** - Docstrings are self-contained; the AI can generate them using only the function signature and body
2. **100% localized fixes** - Changes are confined to the function/class definition
3. **No behavioral risk** - Docstrings don't affect runtime behavior
4. **Improves codebase quality** - Documentation is critical for maintainability
5. **Clear conventions** - PEP 257 provides unambiguous rules to follow

---

## GitHub Actions Setup

```yaml
- name: Run Pydocstyle
  run: |
    pip install pydocstyle
    pydocstyle app/ --convention=google --add-ignore=D100,D104 --match='(?!test_).*\.py' || true
    pydocstyle app/ --convention=google --add-ignore=D100,D104 --match='(?!test_).*\.py' --count > pydocstyle-output.txt 2>&1 || true
```

### For JSON-like Output (Custom Parsing)

```yaml
- name: Run Pydocstyle
  run: |
    pip install pydocstyle pydocstyle-gitlab-code-quality
    pydocstyle app/ --convention=google --add-ignore=D100,D104 | python -c "
    import sys
    import json
    results = []
    for line in sys.stdin:
        if line.strip() and ':' in line:
            parts = line.strip().split(':')
            if len(parts) >= 3:
                results.append({
                    'file': parts[0],
                    'line': int(parts[1]) if parts[1].isdigit() else 0,
                    'code': parts[2].strip().split()[0] if parts[2].strip() else '',
                    'message': ':'.join(parts[2:]).strip()
                })
    print(json.dumps(results, indent=2))
    " > pydocstyle-output.json || true
```

### Arguments Explained

| Argument | Value | Rationale |
|----------|-------|-----------|
| `--convention` | `google` | Google style is widely adopted and readable. Alternatives: `numpy`, `pep257`. |
| `--add-ignore` | `D100,D104` | D100 = missing module docstring, D104 = missing package docstring. These are noisy and lower value. |
| `--match` | `(?!test_).*\.py` | Skip test files - test docstrings are less critical and often intentionally minimal. |

### Convention Options

| Convention | Style | Best For |
|------------|-------|----------|
| `google` | Google Python Style Guide | Most teams, readable format |
| `numpy` | NumPy documentation style | Scientific/data projects |
| `pep257` | Strict PEP 257 | Minimal, standards-focused |

**Recommendation:** Start with `google` - it's the most balanced and widely understood.

---

## Common Error Codes

| Code | Description | Fix Complexity |
|------|-------------|----------------|
| D100 | Missing module docstring | Low |
| D101 | Missing class docstring | Low |
| D102 | Missing method docstring | Low |
| D103 | Missing function docstring | Low |
| D200 | One-line docstring should fit on one line | Very Low |
| D201 | No blank line before function docstring | Very Low |
| D400 | First line should end with period | Very Low |
| D401 | First line should be imperative mood | Low |

### Priority for Implementation

**Phase 1 (High Value, Easy Fix):**
- D101, D102, D103 - Missing docstrings (AI generates full docstring)
- D200, D400 - Formatting fixes (simple string manipulation)

**Phase 2 (Medium Complexity):**
- D401 - Imperative mood (requires understanding the function's purpose)
- D100 - Module docstrings (needs module-level context)

---

## Output Format

Pydocstyle default output:
```
app/utils/helpers.py:42 in public function `calculate_total`:
        D103: Missing docstring in public function
app/models/user.py:15 in public class `User`:
        D101: Missing docstring in public class
```

### Parsed JSON Structure

```json
[
  {
    "file": "app/utils/helpers.py",
    "line": 42,
    "code": "D103",
    "type": "function",
    "name": "calculate_total",
    "message": "Missing docstring in public function"
  }
]
```

### Mapping to Signal Object

```python
signal = Signal(
    tool="pydocstyle",
    file_path=item["file"],
    line_number=item["line"],
    severity="info",  # Docstrings are quality, not correctness
    message=item["message"],
    rule_code=item["code"],
    target_name=item["name"]
)
```

---

## Implementation Steps

### 1. Add Pydocstyle Parser Module

Create `src/parsers/pydocstyle_parser.py`:
- Parse output (convert to JSON structure)
- Extract function/class name from message
- Convert to Signal objects

### 2. Add Docstring Generator

This is where the AI shines. For each missing docstring signal:

1. Read the function/class definition
2. Analyze parameters, return type, and logic
3. Generate appropriate docstring in configured style (Google/NumPy)

**Key considerations:**
- Match the project's existing docstring style
- Include parameter descriptions with types
- Include return value description
- Add Raises section if exceptions are raised

### 3. Docstring Generation Prompt Template

```python
DOCSTRING_PROMPT = """
Generate a Google-style docstring for the following Python {type}:

```python
{code}
```

Requirements:
- First line: imperative mood summary ending with period
- Args section: describe each parameter with type
- Returns section: describe return value with type
- Raises section: list exceptions if any are raised
- Keep it concise but informative

Return only the docstring content (without the triple quotes).
"""
```

### 4. Fix Application Strategy

For missing docstrings (D101, D102, D103):
- Insert docstring immediately after the `def` or `class` line
- Maintain proper indentation (function body indentation level)
- Use triple double-quotes (`"""`)

For formatting issues (D200, D400, D401):
- Extract existing docstring
- Apply the specific fix (add period, reformat to one line, etc.)
- Replace in-place

### 5. Integration Checklist

- [ ] Create `pydocstyle_parser.py` in parsers module
- [ ] Add pydocstyle to tool dependencies
- [ ] Create docstring generation logic with style support
- [ ] Add formatting fix logic for simple violations
- [ ] Add pydocstyle step to GitHub Actions workflow
- [ ] Configure convention and ignored rules
- [ ] Write tests for parser and docstring generation

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Generic/unhelpful docstrings | Medium | Include function body in context, review generated content |
| Incorrect parameter documentation | Low | Parse function signature, cross-reference with body |
| Style mismatch with existing docs | Low | Detect existing style, configure accordingly |

---

## Example Fix Generation

**Input Signal:**
```json
{
  "file": "app/utils/helpers.py",
  "line": 42,
  "code": "D103",
  "name": "calculate_total",
  "message": "Missing docstring in public function"
}
```

**Function Code:**
```python
def calculate_total(items: list[Item], tax_rate: float = 0.1) -> float:
    subtotal = sum(item.price for item in items)
    return subtotal * (1 + tax_rate)
```

**Generated Fix:**
```python
def calculate_total(items: list[Item], tax_rate: float = 0.1) -> float:
    """Calculate the total price including tax.

    Args:
        items: List of items to sum prices for.
        tax_rate: Tax rate to apply as decimal. Defaults to 0.1.

    Returns:
        Total price with tax applied.
    """
    subtotal = sum(item.price for item in items)
    return subtotal * (1 + tax_rate)
```

---

## Estimated Implementation Effort

- Parser module: ~2 hours
- Docstring generator (basic): ~4 hours
- Formatting fixes: ~2 hours
- Style configuration: ~1 hour
- **Total: ~9 hours**

**Ease of Implementation: 90/100**

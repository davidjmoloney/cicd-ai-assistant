# Bandit Integration Plan

## Tool Overview

**Bandit** is a security-focused static analysis tool for Python. It finds common security issues including:
- Hardcoded passwords and secrets
- SQL injection vulnerabilities
- Use of dangerous functions (`eval`, `exec`, `pickle`)
- Weak cryptographic practices
- Shell injection risks
- Insecure SSL/TLS usage

### Why It's a Good Fit

1. **Security is critical** - Security issues are high-priority and justify AI-assisted fixes
2. **Mostly localized fixes** - Most security issues can be fixed within the affected function
3. **Clear remediation patterns** - Each issue type has well-known fix patterns
4. **Excellent JSON output** - Structured data for easy parsing
5. **Complements ruff** - While ruff has some `S` rules, bandit is more comprehensive

### Ruff Overlap Note

Ruff includes bandit rules under the `S` prefix. Before implementing, audit your ruff config:
```toml
# pyproject.toml
[tool.ruff.lint]
select = ["S"]  # If enabled, some overlap exists
```

**Recommendation:** Use bandit for deeper security analysis, or if you want more detailed security context in findings.

---

## GitHub Actions Setup

```yaml
- name: Run Bandit
  run: |
    pip install bandit
    bandit -r app/ -f json -o bandit-output.json \
      --severity-level medium \
      --confidence-level medium \
      --exclude "*/tests/*" \
      -s B101 || true
```

### Arguments Explained

| Argument | Value | Rationale |
|----------|-------|-----------|
| `-r` | `app/` | Recursive scan of target directory |
| `-f json` | - | JSON output for parsing |
| `--severity-level` | `medium` | Report medium and high severity. Low severity is often noisy. |
| `--confidence-level` | `medium` | Report medium and high confidence. Reduces false positives. |
| `--exclude` | `*/tests/*` | Test files often have intentional "insecure" patterns for testing |
| `-s B101` | - | Skip B101 (assert usage) - asserts in non-test code are a style choice, not security |

### Stricter Production Settings

```yaml
bandit -r app/ -f json -o bandit-output.json \
  --severity-level low \
  --confidence-level high \
  -ll \
  --exclude "*/tests/*,*/migrations/*"
```

Use `-ll` (very low noise) for initial rollout, then relax as you address findings.

---

## Common Issue Codes

### High Priority (Security Critical)

| Code | Description | Fix Complexity |
|------|-------------|----------------|
| B105 | Hardcoded password string | Low - use env var |
| B106 | Hardcoded password as function arg | Low - use env var |
| B107 | Hardcoded password default | Low - use env var |
| B608 | SQL injection | Medium - parameterize query |
| B602 | Shell injection via subprocess | Medium - use list args |
| B307 | Use of eval() | Medium - refactor to safe alternative |

### Medium Priority

| Code | Description | Fix Complexity |
|------|-------------|----------------|
| B311 | Random for cryptographic use | Low - use secrets module |
| B324 | Insecure hash function (MD5/SHA1) | Low - use SHA256+ |
| B501 | Request without certificate validation | Low - enable verification |
| B506 | Unsafe YAML load | Low - use safe_load |

### Lower Priority (Context-Dependent)

| Code | Description | Fix Complexity |
|------|-------------|----------------|
| B101 | Assert used | Very Low - but often intentional |
| B104 | Binding to all interfaces | Low - but may be intentional |
| B110 | Try/except/pass | Low - but may be intentional |

---

## Output Format

Bandit JSON output structure:
```json
{
  "results": [
    {
      "filename": "app/db/queries.py",
      "line_number": 42,
      "issue_confidence": "HIGH",
      "issue_severity": "HIGH",
      "issue_text": "Possible SQL injection vector through string-based query construction.",
      "test_id": "B608",
      "test_name": "hardcoded_sql_expressions",
      "code": "    query = f\"SELECT * FROM users WHERE id = {user_id}\"\n",
      "more_info": "https://bandit.readthedocs.io/en/latest/plugins/b608_hardcoded_sql_expressions.html"
    }
  ],
  "metrics": {
    "SEVERITY": {"HIGH": 1},
    "CONFIDENCE": {"HIGH": 1}
  }
}
```

### Mapping to Signal Object

```python
signal = Signal(
    tool="bandit",
    file_path=result["filename"],
    line_number=result["line_number"],
    severity=result["issue_severity"].lower(),  # high, medium, low
    confidence=result["issue_confidence"].lower(),
    message=result["issue_text"],
    rule_code=result["test_id"],
    rule_name=result["test_name"],
    code_snippet=result["code"],
    reference_url=result["more_info"]
)
```

---

## Implementation Steps

### 1. Add Bandit Parser Module

Create `src/parsers/bandit_parser.py`:
- Parse JSON output from bandit
- Filter by severity and confidence thresholds
- Convert to Signal objects

### 2. Add Security Fix Generator

Each bandit rule has a standard remediation pattern:

**B105/B106/B107 - Hardcoded Passwords:**
```python
# Before
password = "secret123"

# After
import os
password = os.environ.get("PASSWORD")
```

**B608 - SQL Injection:**
```python
# Before
query = f"SELECT * FROM users WHERE id = {user_id}"

# After
query = "SELECT * FROM users WHERE id = %s"
cursor.execute(query, (user_id,))
```

**B506 - Unsafe YAML:**
```python
# Before
data = yaml.load(file)

# After
data = yaml.safe_load(file)
```

### 3. Fix Complexity Categorization

Categorize fixes by invasiveness:

**Simple Fixes (Single-line replacement):**
- B311: `random.random()` → `secrets.token_bytes()`
- B324: `hashlib.md5()` → `hashlib.sha256()`
- B501: `verify=False` → `verify=True`
- B506: `yaml.load()` → `yaml.safe_load()`

**Medium Fixes (Multi-line, same function):**
- B105-107: Extract to environment variable
- B602: Convert shell string to list arguments
- B307: Refactor eval() usage

**Complex Fixes (May require broader changes):**
- B608: SQL parameterization (might affect multiple functions)

**Recommendation:** Start with simple fixes, flag complex fixes for human review.

### 4. Context Gathering Strategy

For security fixes, gather:
1. The affected code block (function containing the issue)
2. Import statements (to check for existing imports like `os`, `secrets`)
3. For SQL issues: the database library being used (sqlite3, psycopg2, SQLAlchemy)

### 5. Integration Checklist

- [ ] Create `bandit_parser.py` in parsers module
- [ ] Add bandit to tool dependencies
- [ ] Create fix patterns for common issues (B105-107, B311, B324, B501, B506)
- [ ] Add bandit step to GitHub Actions workflow
- [ ] Configure severity/confidence thresholds
- [ ] Create remediation templates for each issue type
- [ ] Add "human review required" flag for complex issues
- [ ] Write tests for parser and fix generation

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Fix breaks functionality | Medium | Test generated fixes, flag complex patterns for review |
| SQL fix requires multi-file changes | Medium | Detect scope, flag if cross-function |
| Environment variable doesn't exist | Medium | Generate both code fix and setup instructions |
| False positive in intentional patterns | Low | Allow inline `# nosec` comments |

---

## Example Fix Generation

### Example 1: Hardcoded Password (Simple)

**Input Signal:**
```json
{
  "filename": "app/config/settings.py",
  "line_number": 15,
  "test_id": "B105",
  "issue_text": "Possible hardcoded password: 'mysecretpassword'",
  "code": "DB_PASSWORD = \"mysecretpassword\"\n"
}
```

**Generated Fix:**
```python
# Before:
DB_PASSWORD = "mysecretpassword"

# After:
import os
DB_PASSWORD = os.environ.get("DB_PASSWORD")
```

**Additional Output:**
```
⚠️  Remember to set the DB_PASSWORD environment variable in your deployment configuration.
```

### Example 2: SQL Injection (Medium)

**Input Signal:**
```json
{
  "filename": "app/db/queries.py",
  "line_number": 42,
  "test_id": "B608",
  "issue_text": "Possible SQL injection vector through string-based query construction.",
  "code": "    query = f\"SELECT * FROM users WHERE id = {user_id}\"\n    cursor.execute(query)\n"
}
```

**Generated Fix:**
```python
# Before:
query = f"SELECT * FROM users WHERE id = {user_id}"
cursor.execute(query)

# After:
query = "SELECT * FROM users WHERE id = %s"
cursor.execute(query, (user_id,))
```

---

## Estimated Implementation Effort

- Parser module: ~2 hours
- Simple fix patterns (B311, B324, B501, B506): ~3 hours
- Password extraction fixes (B105-107): ~3 hours
- SQL injection fixes (B608): ~4 hours (more complex)
- Testing: ~2 hours
- **Total: ~14 hours**

**Ease of Implementation: 80/100**

(Higher effort than vulture/pydocstyle due to variety of fix patterns, but still very tractable)

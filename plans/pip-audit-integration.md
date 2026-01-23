# pip-audit Integration Plan

## Tool Overview

**pip-audit** is a tool for scanning Python dependencies for known security vulnerabilities. It checks installed packages against:
- PyPI Advisory Database
- OSV (Open Source Vulnerabilities) database
- GitHub Advisory Database

### Why It's a Good Fit

1. **Critical security value** - Vulnerable dependencies are a major attack vector
2. **Simple fixes for most cases** - Usually just updating a version number
3. **Excellent JSON output** - Structured vulnerability data
4. **Clear remediation** - Fixed versions are provided in the output
5. **Works with existing requirements** - Scans requirements.txt, pyproject.toml, or installed packages

### Consideration: Overlap with Dependabot

If your repository uses GitHub Dependabot, there's overlap. However, pip-audit in CI/CD provides:
- Immediate feedback on PR dependency changes
- Integration with your AI assistant for automated fixes
- Consistent scanning approach with other tools

---

## GitHub Actions Setup

```yaml
- name: Run pip-audit
  run: |
    pip install pip-audit
    pip-audit -r app/requirements.txt \
      --format json \
      --output pip-audit-output.json \
      --desc on \
      --progress-spinner off || true
```

### Alternative: Scan Installed Packages

```yaml
- name: Run pip-audit
  run: |
    pip install pip-audit
    pip install -r app/requirements.txt
    pip-audit \
      --format json \
      --output pip-audit-output.json \
      --desc on \
      --progress-spinner off || true
```

### Arguments Explained

| Argument | Value | Rationale |
|----------|-------|-----------|
| `-r` | `requirements.txt` | Scan specific requirements file |
| `--format json` | - | JSON output for parsing |
| `--output` | `pip-audit-output.json` | Output file path |
| `--desc on` | - | Include vulnerability descriptions (helpful for AI context) |
| `--progress-spinner off` | - | Disable spinner for CI environments |
| `--strict` | (optional) | Fail on any vulnerability (use if blocking PRs) |

### For pyproject.toml Projects

```yaml
pip-audit --format json --output pip-audit-output.json --desc on
```

(When run without `-r`, pip-audit scans the current environment)

---

## Vulnerability Severity Levels

pip-audit doesn't filter by severity in CLI, but the output includes it:

| Severity | Action |
|----------|--------|
| CRITICAL | Immediate fix required |
| HIGH | Fix in current sprint |
| MEDIUM | Fix when convenient |
| LOW | Track, fix if easy |

Consider filtering in your parser based on project requirements.

---

## Output Format

pip-audit JSON output structure:
```json
{
  "dependencies": [
    {
      "name": "requests",
      "version": "2.25.0",
      "vulns": [
        {
          "id": "GHSA-j8r2-6x86-q33q",
          "fix_versions": ["2.31.0"],
          "description": "Requests vulnerable to leaked proxy credentials in redirects"
        }
      ]
    },
    {
      "name": "django",
      "version": "3.2.0",
      "vulns": []
    }
  ],
  "fixes": [
    {
      "name": "requests",
      "old_version": "2.25.0",
      "new_version": "2.31.0"
    }
  ]
}
```

### Mapping to Signal Object

```python
for dep in output["dependencies"]:
    for vuln in dep["vulns"]:
        signal = Signal(
            tool="pip-audit",
            file_path="requirements.txt",  # or pyproject.toml
            line_number=None,  # Determine by parsing requirements file
            severity=vuln.get("severity", "unknown"),
            message=f"{dep['name']}=={dep['version']} has vulnerability: {vuln['description']}",
            package_name=dep["name"],
            current_version=dep["version"],
            fixed_versions=vuln["fix_versions"],
            vuln_id=vuln["id"]
        )
```

---

## Implementation Steps

### 1. Add pip-audit Parser Module

Create `src/parsers/pip_audit_parser.py`:
- Parse JSON output
- Find line numbers in requirements.txt for each package
- Convert to Signal objects with fix version information

### 2. Requirements File Locator

Detect the requirements file format:
```python
def find_requirements_file(repo_path: str) -> tuple[str, str]:
    """Returns (file_path, file_type)"""
    candidates = [
        ("requirements.txt", "requirements"),
        ("requirements/base.txt", "requirements"),
        ("pyproject.toml", "pyproject"),
        ("setup.py", "setup"),
    ]
    for path, file_type in candidates:
        full_path = os.path.join(repo_path, path)
        if os.path.exists(full_path):
            return full_path, file_type
    return None, None
```

### 3. Add Dependency Update Generator

**For requirements.txt:**
```python
# Before:
requests==2.25.0

# After:
requests==2.31.0
```

**For pyproject.toml:**
```toml
# Before:
dependencies = [
    "requests>=2.25.0",
]

# After:
dependencies = [
    "requests>=2.31.0",
]
```

### 4. Line Number Detection

Parse the requirements file to find the exact line:
```python
def find_package_line(requirements_path: str, package_name: str) -> int:
    with open(requirements_path) as f:
        for i, line in enumerate(f, 1):
            # Handle various formats: pkg==1.0, pkg>=1.0, pkg~=1.0
            if line.strip().lower().startswith(package_name.lower()):
                return i
    return None
```

### 5. Fix Complexity Assessment

| Scenario | Complexity | Action |
|----------|------------|--------|
| Patch version bump (2.25.0 → 2.25.1) | Very Low | Auto-fix |
| Minor version bump (2.25.0 → 2.31.0) | Low | Auto-fix with note |
| Major version bump (2.x → 3.x) | High | Flag for review |
| No fix available | N/A | Alert only, no fix |

### 6. Breaking Change Detection

For major version bumps, add a warning:
```python
def is_major_bump(old: str, new: str) -> bool:
    old_major = int(old.split('.')[0])
    new_major = int(new.split('.')[0])
    return new_major > old_major
```

### 7. Integration Checklist

- [ ] Create `pip_audit_parser.py` in parsers module
- [ ] Add pip-audit to tool dependencies
- [ ] Create requirements file locator (txt, toml support)
- [ ] Create line number detection for packages
- [ ] Create version update fix generator
- [ ] Add major version bump warning logic
- [ ] Add pip-audit step to GitHub Actions workflow
- [ ] Write tests for parser and fix generation

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Major version has breaking changes | Medium | Detect major bumps, flag for review |
| Fix version conflicts with other deps | Medium | Note that user should run `pip install` to verify |
| No fix available yet | Low | Report vulnerability, skip fix generation |
| Package pinned for compatibility reasons | Low | Check for comments explaining pins |

---

## Example Fix Generation

### Example 1: Simple Patch Update

**Input Signal:**
```json
{
  "package_name": "requests",
  "current_version": "2.25.0",
  "fixed_versions": ["2.31.0"],
  "vuln_id": "GHSA-j8r2-6x86-q33q",
  "message": "Requests vulnerable to leaked proxy credentials"
}
```

**requirements.txt Before:**
```
flask==2.0.1
requests==2.25.0
sqlalchemy==1.4.0
```

**Generated Fix:**
```
flask==2.0.1
requests==2.31.0
sqlalchemy==1.4.0
```

### Example 2: Major Version Update (Flag for Review)

**Input Signal:**
```json
{
  "package_name": "django",
  "current_version": "2.2.0",
  "fixed_versions": ["3.2.15", "4.0.8"],
  "vuln_id": "CVE-2022-xxxxx"
}
```

**Generated Output:**
```
⚠️  MAJOR VERSION UPDATE REQUIRED

Package: django
Current: 2.2.0
Fixed versions: 3.2.15, 4.0.8

This is a major version bump which may include breaking changes.
Please review the Django release notes before applying this fix.

Recommended fix (smallest major bump):
  django==3.2.15

Flag: REQUIRES_HUMAN_REVIEW
```

---

## Additional Considerations

### Lock Files

If the project uses lock files (poetry.lock, Pipfile.lock, requirements.lock):
- Update the source file (pyproject.toml, Pipfile, requirements.in)
- Note that user needs to regenerate lock file

```
⚠️  This project uses a lock file. After applying this fix, run:
    poetry lock
    # or
    pip-compile requirements.in
```

### Transitive Dependencies

pip-audit may flag transitive dependencies. For these:
- Identify which direct dependency pulls in the vulnerable package
- Suggest updating the direct dependency if possible
- Note if the fix requires updating the transitive dep directly

---

## Estimated Implementation Effort

- Parser module: ~2 hours
- Requirements file locator: ~1 hour
- Line number detection: ~1 hour
- Version update generator: ~2 hours
- Major version detection/warnings: ~1 hour
- Testing: ~2 hours
- **Total: ~9 hours**

**Ease of Implementation: 75/100**

(Lower than others due to variety of requirements file formats and edge cases around version compatibility)

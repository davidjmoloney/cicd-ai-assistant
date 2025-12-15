# Simple AI Code Assistant Architecture for Ardessa
## Based on Academic Literature Review

**Created**: 2025-11-27
**Purpose**: Practical, implementable architecture for AI assistant that ingests CI/CD signals and generates PRs

---

## Design Philosophy

This architecture prioritizes:
- **Simplicity**: Easy to understand and implement
- **Modularity**: Components can be built and tested independently
- **Evidence-based**: Grounded in proven academic approaches
- **Practical**: Uses off-the-shelf LLMs (GPT-4/Claude) without fine-tuning

---

## Primary Literature Foundation

### Core Architecture: LLMLOOP (Ravi et al., 2025)
**Why this paper**: Demonstrates the clearest iterative feedback loop architecture using CI/CD signals (compilation, tests, static analysis) to improve code.

**Key concept adopted**: Sequential feedback loops where each CI/CD signal triggers a specialized refinement cycle.

### Supporting Pattern: AI-Augmented CI/CD Pipelines (Baqar et al., 2025)
**Why this paper**: Provides the specialized agent pattern and decision taxonomy for CI/CD stages.

**Key concept adopted**: Specialized agents for different signal types (Test-Triage, Security) with policy-bounded actions.

### Implementation Guidance: AutoCodeRover (Zhang et al., 2024)
**Why this paper**: Demonstrates practical tool integration and autonomous agent structure with finite state machine.

**Key concept adopted**: Tool-based agent interaction and structured prompt management.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    CI/CD PIPELINE                           │
│  (GitHub Actions / GitLab CI / Jenkins)                     │
└─────────────────┬───────────────────────────────────────────┘
                  │ Triggers Github action sitting in this project
                  ↓
┌─────────────────────────────────────────────────────────────┐
│              SIGNAL COLLECTION MODULE                       │
│  - Downloads CI/CD artifacts                                │
│  - Parse structured objects                                 │
│  - Passes to Orchestrator                                   │
└─────────────────┬───────────────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────────────┐
│              AGENT ORCHESTRATOR                              │
│  - Routes signal objects to specialized agents               │
│  - Manages agent execution order                             │
│  - Aggregates agent outputs                                  │
└─────────────────┬───────────────────────────────────────────┘
                  │
      ┌───────────┼───────────┬───────────┬───────────┐
      ↓           ↓           ↓           ↓           ↓
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│  Test    │ │ Coverage │ │   Lint   │ │ Security │ │Integration│
│  Agent   │ │  Agent   │ │  Agent   │ │  Agent   │ │   Agent  │
└────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
     │            │            │            │            │
     └────────────┴────────────┴────────────┴────────────┘
                              │
                              ↓
                    ┌──────────────────┐
                    │  LLM Interface   │
                    │  (GPT-4/Claude)  │
                    └────────┬─────────┘
                             │
                             ↓
                    ┌──────────────────┐
                    │   Code Editor    │
                    │   - Read files   │
                    │   - Write fixes  │
                    │   - Run tests    │
                    └────────┬─────────┘
                             │
                             ↓
                    ┌──────────────────┐
                    │  PR Generator    │
                    │  - Create branch │
                    │  - Commit fixes  │
                    │  - Open PR       │
                    └──────────────────┘
```

---

## Component Specifications

### 1. Signal Collection Service

**Literature basis**: AIDOaRt (Eramo et al., 2021) - Data Collection & Representation layer

**Purpose**: Parse CI/CD outputs into structured, actionable signals

**Inputs**:
- CI/CD pipeline artifacts (logs, reports, JSON outputs)
- Webhook payloads from CI/CD platform

**Outputs**: Structured signal objects

**Implementation**:
```python
class Signal:
    signal_type: str  # 'unit_test', 'coverage', 'lint', 'security', 'integration'
    severity: str     # 'critical', 'high', 'medium', 'low'
    details: dict     # Type-specific data
    file_paths: list  # Affected files
    timestamp: datetime
    commit_sha: str
```

**Signal Types**:

1. **Unit Test Failures**
   ```python
   {
       "signal_type": "unit_test",
       "severity": "high",
       "details": {
           "test_name": "test_user_authentication",
           "failure_message": "AssertionError: Expected 200, got 401",
           "stack_trace": "...",
           "file": "tests/test_auth.py",
           "line": 42
       },
       "file_paths": ["src/auth.py", "tests/test_auth.py"]
   }
   ```

2. **Coverage Drops**
   ```python
   {
       "signal_type": "coverage",
       "severity": "medium",
       "details": {
           "file": "src/payment.py",
           "current_coverage": 45.2,
           "previous_coverage": 67.8,
           "uncovered_lines": [23, 24, 25, 56, 57],
           "missing_tests": ["test_refund_flow", "test_partial_payment"]
       },
       "file_paths": ["src/payment.py"]
   }
   ```

3. **Lint Violations**
   ```python
   {
       "signal_type": "lint",
       "severity": "low",
       "details": {
           "rule": "E501",
           "message": "line too long (120 > 79 characters)",
           "file": "src/utils.py",
           "line": 15,
           "column": 80
       },
       "file_paths": ["src/utils.py"]
   }
   ```

4. **Security Issues**
   ```python
   {
       "signal_type": "security",
       "severity": "critical",
       "details": {
           "vulnerability": "SQL Injection",
           "cwe": "CWE-89",
           "description": "User input directly concatenated into SQL query",
           "file": "src/database.py",
           "line": 78,
           "recommendation": "Use parameterized queries"
       },
       "file_paths": ["src/database.py"]
   }
   ```

5. **Integration Test Failures**
   ```python
   {
       "signal_type": "integration",
       "severity": "high",
       "details": {
           "test_name": "test_checkout_flow",
           "failure_type": "timeout",
           "message": "Request to /api/checkout timed out after 30s",
           "affected_services": ["checkout-service", "payment-gateway"]
       },
       "file_paths": ["src/services/checkout.py", "src/services/payment.py"]
   }
   ```

**Parsers Required**:
- JUnit XML parser (for test results)
- Coverage.py JSON parser
- ESLint/Pylint JSON output parser
- SARIF parser (for security scanners like Semgrep, CodeQL)
- Custom integration test log parser

---

### 2. Agent Orchestrator

**Literature basis**: AI-Augmented CI/CD Pipelines (Baqar et al., 2025) - Agent coordination with policy-bounded execution

**Purpose**: Route signals to appropriate agents and manage execution

**Key Logic** (from LLMLOOP sequential approach):

```python
class AgentOrchestrator:
    def process_signals(self, signals: List[Signal]) -> List[PRProposal]:
        # Group signals by severity and type
        prioritized_signals = self.prioritize(signals)

        pr_proposals = []

        # Process in order of severity (CRITICAL → HIGH → MEDIUM → LOW)
        for signal in prioritized_signals:
            agent = self.get_agent(signal.signal_type)

            # Each agent attempts to fix the issue
            fix_result = agent.process(signal)

            if fix_result.success:
                pr_proposals.append(fix_result.pr_proposal)

        return pr_proposals

    def prioritize(self, signals: List[Signal]) -> List[Signal]:
        """
        Priority order (from AI-Augmented CI/CD paper decision taxonomy):
        1. CRITICAL security issues (always fix first)
        2. HIGH severity test failures (blocking)
        3. HIGH severity integration failures
        4. MEDIUM coverage drops
        5. LOW lint issues
        """
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        return sorted(signals, key=lambda s: severity_order[s.severity])
```

**Policy Boundaries** (from AI-Augmented CI/CD paper):
- Never deploy with CRITICAL security issues
- Never fix more than 3 issues in single PR (maintainability)
- Require minimum 80% confidence score for autonomous fixes
- Always include test validation before proposing PR

---

### 3. Specialized Agents

**Literature basis**:
- LLMLOOP (feedback loop structure)
- AutoCodeRover (tool integration and prompt structure)
- AI-Augmented CI/CD Pipelines (specialized agent roles)

**Common Agent Structure**:

```python
class BaseAgent:
    def __init__(self, llm_client, code_tools):
        self.llm = llm_client  # GPT-4 or Claude API client
        self.tools = code_tools
        self.max_iterations = 3  # From LLMLOOP: limit iteration cycles

    def process(self, signal: Signal) -> FixResult:
        """
        Three-stage process from LLMLOOP:
        1. Understand the issue
        2. Generate fix
        3. Validate fix
        """
        # Stage 1: Understand
        context = self.gather_context(signal)

        # Stage 2: Generate fix (with iteration)
        for attempt in range(self.max_iterations):
            fix = self.generate_fix(signal, context)

            # Stage 3: Validate
            validation = self.validate_fix(fix, signal)

            if validation.passed:
                return FixResult(
                    success=True,
                    fix=fix,
                    confidence=validation.confidence,
                    pr_proposal=self.create_pr_proposal(fix, signal)
                )

            # Update context with failure feedback (LLMLOOP iterative approach)
            context.add_failure(validation.feedback)

        return FixResult(success=False, reason="Max iterations exceeded")
```

**Agent-Specific Implementations**:

#### Test Agent
**Purpose**: Fix failing unit tests

**Literature basis**: MarsCode Agent - dynamic debugging with test execution feedback

```python
class TestAgent(BaseAgent):
    def gather_context(self, signal: Signal) -> Context:
        """Gather relevant context for test failure"""
        context = Context()

        # 1. Read the failing test
        test_file = signal.details['file']
        context.test_code = self.tools.read_file(test_file)

        # 2. Read the code under test
        source_file = self.infer_source_file(test_file)
        context.source_code = self.tools.read_file(source_file)

        # 3. Get failure details
        context.failure_message = signal.details['failure_message']
        context.stack_trace = signal.details['stack_trace']

        return context

    def generate_fix(self, signal: Signal, context: Context) -> Fix:
        """Use LLM to generate fix"""
        prompt = f"""
You are a software engineer fixing a failing unit test.

**Test File**: {context.test_code[:500]}...

**Source Code**: {context.source_code[:500]}...

**Failure Message**: {context.failure_message}

**Stack Trace**: {context.stack_trace[:300]}...

Analyze the failure and propose a fix to the SOURCE CODE (not the test).
Generate a JSON patch with the changes.

Previous failed attempts: {context.failures}

Response format:
{{
    "analysis": "Brief explanation of the bug",
    "fix_location": {{"file": "...", "line": ...}},
    "fix_code": "The corrected code",
    "confidence": 0.0-1.0
}}
"""

        response = self.llm.generate(prompt)
        return Fix.from_json(response)

    def validate_fix(self, fix: Fix, signal: Signal) -> Validation:
        """Run tests to validate fix"""
        # Apply fix temporarily
        self.tools.apply_patch(fix)

        # Run the specific failing test
        test_result = self.tools.run_tests([signal.details['test_name']])

        # Rollback if failed
        if not test_result.passed:
            self.tools.rollback_patch(fix)
            return Validation(
                passed=False,
                feedback=f"Test still failing: {test_result.message}"
            )

        # Run all related tests to avoid regression
        all_tests = self.tools.run_tests(self.tools.find_related_tests(fix.file))

        if not all_tests.passed:
            self.tools.rollback_patch(fix)
            return Validation(
                passed=False,
                feedback=f"Fix caused regression: {all_tests.failures}"
            )

        return Validation(passed=True, confidence=fix.confidence)
```

#### Coverage Agent
**Purpose**: Generate tests to improve coverage

**Literature basis**: LLMLOOP - automated test generation with iterative refinement

```python
class CoverageAgent(BaseAgent):
    def gather_context(self, signal: Signal) -> Context:
        context = Context()

        # Read source code with uncovered lines
        source_file = signal.details['file']
        context.source_code = self.tools.read_file(source_file)

        # Get existing tests for reference
        test_file = self.tools.find_test_file(source_file)
        if test_file:
            context.existing_tests = self.tools.read_file(test_file)

        # Mark uncovered lines
        context.uncovered_lines = signal.details['uncovered_lines']

        return context

    def generate_fix(self, signal: Signal, context: Context) -> Fix:
        prompt = f"""
You are writing unit tests to improve code coverage.

**Source Code** (lines {context.uncovered_lines} are NOT covered):
{context.source_code}

**Existing Tests** (for reference):
{context.existing_tests[:300] if context.existing_tests else "None"}

**Missing Test Cases**: {signal.details['missing_tests']}

Generate NEW test functions that cover the uncovered lines.
Follow the existing test style and naming conventions.

Response format:
{{
    "test_functions": [
        {{
            "name": "test_...",
            "code": "def test_...(): ...",
            "covers_lines": [23, 24, 25]
        }}
    ],
    "confidence": 0.0-1.0
}}
"""
        response = self.llm.generate(prompt)
        return Fix.from_json(response)

    def validate_fix(self, fix: Fix, signal: Signal) -> Validation:
        """Validate that new tests pass and improve coverage"""
        # Add new tests
        self.tools.append_to_file(fix.test_file, fix.test_code)

        # Run new tests
        test_result = self.tools.run_tests([t['name'] for t in fix.test_functions])

        if not test_result.passed:
            self.tools.rollback_patch(fix)
            return Validation(
                passed=False,
                feedback=f"Generated tests fail: {test_result.message}"
            )

        # Measure coverage improvement
        new_coverage = self.tools.measure_coverage(signal.details['file'])

        if new_coverage <= signal.details['current_coverage']:
            self.tools.rollback_patch(fix)
            return Validation(
                passed=False,
                feedback="Tests didn't improve coverage"
            )

        return Validation(
            passed=True,
            confidence=fix.confidence,
            metadata={'coverage_improvement': new_coverage - signal.details['current_coverage']}
        )
```

#### Lint Agent
**Purpose**: Fix code style violations

**Literature basis**: Augmenting LLMs with Static Analysis (Abtahi & Azim, 2025)

```python
class LintAgent(BaseAgent):
    def gather_context(self, signal: Signal) -> Context:
        context = Context()

        # Read file with lint issue
        context.file_content = self.tools.read_file(signal.details['file'])
        context.violation_line = signal.details['line']
        context.rule = signal.details['rule']
        context.message = signal.details['message']

        return context

    def generate_fix(self, signal: Signal, context: Context) -> Fix:
        # For simple lint issues, often a direct fix without LLM
        # (from Augmenting LLMs paper - use LLM only when needed)

        if self.is_simple_fix(signal.details['rule']):
            return self.apply_direct_fix(signal, context)

        # For complex lint issues, use LLM
        prompt = f"""
Fix the following lint violation:

**Rule**: {context.rule}
**Message**: {context.message}
**Line {context.violation_line}**: {self.tools.get_line(context.file_content, context.violation_line)}

**Context** (5 lines before and after):
{self.tools.get_lines(context.file_content, context.violation_line - 5, context.violation_line + 5)}

Provide the corrected line(s).

Response format:
{{
    "corrected_lines": {{"line_number": "corrected code"}},
    "confidence": 0.0-1.0
}}
"""
        response = self.llm.generate(prompt)
        return Fix.from_json(response)

    def validate_fix(self, fix: Fix, signal: Signal) -> Validation:
        """Validate lint fix"""
        # Apply fix
        self.tools.apply_patch(fix)

        # Re-run linter on the file
        lint_result = self.tools.run_linter(signal.details['file'])

        # Check if specific violation is resolved
        if signal.details['rule'] in lint_result.violations:
            self.tools.rollback_patch(fix)
            return Validation(
                passed=False,
                feedback="Lint violation still present"
            )

        # Ensure no new violations introduced
        if len(lint_result.violations) > 0:
            new_violations = [v for v in lint_result.violations if v not in context.original_violations]
            if new_violations:
                self.tools.rollback_patch(fix)
                return Validation(
                    passed=False,
                    feedback=f"Fix introduced new violations: {new_violations}"
                )

        return Validation(passed=True, confidence=fix.confidence)
```

#### Security Agent
**Purpose**: Fix security vulnerabilities

**Literature basis**: AI-Augmented CI/CD Pipelines - Security Agent with CVE severity gating

```python
class SecurityAgent(BaseAgent):
    def gather_context(self, signal: Signal) -> Context:
        context = Context()

        # Read vulnerable code
        context.vulnerable_code = self.tools.read_file(signal.details['file'])
        context.vulnerability_type = signal.details['vulnerability']
        context.cwe = signal.details['cwe']
        context.recommendation = signal.details['recommendation']
        context.line = signal.details['line']

        # Retrieve secure coding examples (RAG from Abtahi & Azim paper)
        context.secure_examples = self.tools.retrieve_secure_patterns(
            vulnerability_type=context.vulnerability_type,
            language=self.tools.detect_language(signal.details['file'])
        )

        return context

    def generate_fix(self, signal: Signal, context: Context) -> Fix:
        prompt = f"""
You are a security engineer fixing a vulnerability.

**Vulnerability**: {context.vulnerability_type} (CWE-{context.cwe})
**Recommendation**: {context.recommendation}

**Vulnerable Code** (line {context.line}):
{self.tools.get_lines(context.vulnerable_code, context.line - 3, context.line + 3)}

**Secure Coding Examples**:
{context.secure_examples[:500]}

Provide a secure fix that addresses the vulnerability without breaking functionality.

Response format:
{{
    "analysis": "Explanation of the vulnerability",
    "fix_code": "Secure replacement code",
    "test_recommendation": "How to verify the fix",
    "confidence": 0.0-1.0
}}
"""
        response = self.llm.generate(prompt)
        return Fix.from_json(response)

    def validate_fix(self, fix: Fix, signal: Signal) -> Validation:
        """Validate security fix"""
        # Apply fix
        self.tools.apply_patch(fix)

        # Re-run security scanner
        scan_result = self.tools.run_security_scan(signal.details['file'])

        # Check if vulnerability is resolved
        if any(v.cwe == signal.details['cwe'] and v.line == signal.details['line']
               for v in scan_result.vulnerabilities):
            self.tools.rollback_patch(fix)
            return Validation(
                passed=False,
                feedback="Vulnerability still detected by scanner"
            )

        # Run tests to ensure functionality preserved
        test_result = self.tools.run_tests(self.tools.find_related_tests(signal.details['file']))

        if not test_result.passed:
            self.tools.rollback_patch(fix)
            return Validation(
                passed=False,
                feedback=f"Security fix broke tests: {test_result.failures}"
            )

        return Validation(passed=True, confidence=fix.confidence)
```

#### Integration Test Agent
**Purpose**: Fix integration test failures

**Literature basis**: MarsCode Agent - multi-file bug fixing approach

```python
class IntegrationAgent(BaseAgent):
    def gather_context(self, signal: Signal) -> Context:
        context = Context()

        # Integration tests often involve multiple services
        context.affected_services = signal.details['affected_services']
        context.failure_type = signal.details['failure_type']
        context.test_name = signal.details['test_name']

        # Read all affected service files
        for service_file in signal.file_paths:
            context.service_code[service_file] = self.tools.read_file(service_file)

        # Get integration test logs
        context.test_logs = self.tools.get_test_logs(signal.details['test_name'])

        return context

    def generate_fix(self, signal: Signal, context: Context) -> Fix:
        prompt = f"""
You are debugging an integration test failure involving multiple services.

**Test**: {context.test_name}
**Failure Type**: {context.failure_type}
**Affected Services**: {context.affected_services}

**Test Logs**:
{context.test_logs[:500]}

**Service Code**:
{self._format_multi_service_code(context.service_code)}

Identify the root cause and propose fixes to the affected services.
This may require changes to multiple files.

Response format:
{{
    "root_cause": "Explanation of the issue",
    "fixes": [
        {{
            "file": "path/to/file.py",
            "changes": "code changes",
            "rationale": "why this change"
        }}
    ],
    "confidence": 0.0-1.0
}}
"""
        response = self.llm.generate(prompt)
        return Fix.from_json(response)

    def validate_fix(self, fix: Fix, signal: Signal) -> Validation:
        """Validate integration test fix"""
        # Apply all fixes (may span multiple files)
        self.tools.apply_multi_file_patch(fix)

        # Run the specific integration test
        test_result = self.tools.run_integration_test(signal.details['test_name'])

        if not test_result.passed:
            self.tools.rollback_multi_file_patch(fix)
            return Validation(
                passed=False,
                feedback=f"Integration test still failing: {test_result.message}"
            )

        # Run all integration tests to check for regressions
        all_integration = self.tools.run_all_integration_tests()

        if not all_integration.passed:
            self.tools.rollback_multi_file_patch(fix)
            return Validation(
                passed=False,
                feedback=f"Fix caused integration regression: {all_integration.failures}"
            )

        return Validation(passed=True, confidence=fix.confidence)
```

---

### 4. Code Tools Library

**Literature basis**: AutoCodeRover (tool-based agent interaction)

**Purpose**: Provide agents with file system and execution capabilities

```python
class CodeTools:
    """
    Abstraction layer for code manipulation and execution
    Based on AutoCodeRover's 14 specialized tools
    """

    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    # File Operations
    def read_file(self, file_path: str) -> str:
        """Read entire file"""
        pass

    def read_lines(self, file_path: str, start: int, end: int) -> str:
        """Read specific line range"""
        pass

    def apply_patch(self, fix: Fix) -> None:
        """Apply code changes from fix"""
        pass

    def rollback_patch(self, fix: Fix) -> None:
        """Revert code changes"""
        pass

    # Test Execution
    def run_tests(self, test_names: List[str]) -> TestResult:
        """Execute specific tests"""
        pass

    def run_all_tests(self) -> TestResult:
        """Execute full test suite"""
        pass

    def run_integration_tests(self) -> TestResult:
        """Execute integration test suite"""
        pass

    # Analysis Tools
    def run_linter(self, file_path: str) -> LintResult:
        """Run linter on file"""
        pass

    def run_security_scan(self, file_path: str) -> SecurityResult:
        """Run security scanner on file"""
        pass

    def measure_coverage(self, file_path: str) -> float:
        """Measure test coverage percentage"""
        pass

    # Code Intelligence
    def find_test_file(self, source_file: str) -> Optional[str]:
        """Locate test file for source file"""
        pass

    def find_related_tests(self, source_file: str) -> List[str]:
        """Find all tests that exercise this source file"""
        pass

    def get_test_logs(self, test_name: str) -> str:
        """Retrieve test execution logs"""
        pass
```

---

### 5. PR Generator

**Literature basis**: MarsCode Agent - automated patch generation and validation

**Purpose**: Create pull requests from validated fixes

```python
class PRGenerator:
    def __init__(self, git_client, repo_owner: str, repo_name: str):
        self.git = git_client
        self.repo_owner = repo_owner
        self.repo_name = repo_name

    def create_pr(self, pr_proposal: PRProposal) -> PullRequest:
        """
        Create PR from validated fix
        Following pattern from AI-Augmented CI/CD paper
        """

        # 1. Create feature branch
        branch_name = f"ai-fix/{pr_proposal.signal_type}/{pr_proposal.issue_id}"
        self.git.create_branch(branch_name)

        # 2. Apply changes
        for change in pr_proposal.changes:
            self.git.apply_change(change)

        # 3. Commit with structured message
        commit_message = self._generate_commit_message(pr_proposal)
        self.git.commit(commit_message)

        # 4. Push branch
        self.git.push(branch_name)

        # 5. Create PR
        pr_body = self._generate_pr_body(pr_proposal)

        pr = self.git.create_pull_request(
            title=pr_proposal.title,
            body=pr_body,
            head=branch_name,
            base="main",
            labels=["ai-generated", pr_proposal.signal_type]
        )

        return pr

    def _generate_commit_message(self, pr_proposal: PRProposal) -> str:
        """
        Generate conventional commit message
        """
        type_map = {
            'unit_test': 'fix',
            'coverage': 'test',
            'lint': 'style',
            'security': 'security',
            'integration': 'fix'
        }

        commit_type = type_map[pr_proposal.signal_type]

        return f"""{commit_type}: {pr_proposal.short_description}

{pr_proposal.detailed_description}

AI-Generated Fix
- Signal: {pr_proposal.signal_type}
- Confidence: {pr_proposal.confidence:.2f}
- Validated: {pr_proposal.validation_status}

Co-authored-by: AI Assistant <ai@ardessa.com>
"""

    def _generate_pr_body(self, pr_proposal: PRProposal) -> str:
        """
        Generate PR description with context
        Based on DeputyDev's PR summary format
        """
        return f"""## AI-Generated Fix

### Issue Detected
**Signal Type**: {pr_proposal.signal_type}
**Severity**: {pr_proposal.severity}

{pr_proposal.issue_description}

### Root Cause Analysis
{pr_proposal.root_cause}

### Changes Made
{pr_proposal.changes_description}

### Validation Results
- ✅ Tests Passed: {pr_proposal.tests_passed}
- ✅ No Regressions: {pr_proposal.no_regressions}
- 📊 Confidence Score: {pr_proposal.confidence:.1%}

### Files Changed
{self._format_file_changes(pr_proposal.file_changes)}

### Testing Instructions
{pr_proposal.testing_instructions}

---

**Note**: This PR was generated automatically by the AI Code Assistant.
Please review carefully before merging.

**Run ID**: {pr_proposal.run_id}
**Generated**: {pr_proposal.timestamp}
"""
```

---

## Execution Flow

**Literature basis**: LLMLOOP's sequential feedback loop approach

### Step-by-Step Process

**Step 1: Ardessa Backend Daily Check (Midnight)**
```
GitHub Actions cron triggers in ardessa/backend
  ↓
Runs: ruff, mypy, bandit
  ↓
Generates: 3 JSON files
  ↓
Uploads as artifacts to GitHub
  ↓
Uses repository_dispatch to trigger ardessa/ai-assistant
```

**Step 2: AI Assistant Receives Trigger (Seconds later)**
```
GitHub Actions in ardessa/ai-assistant starts
  ↓
Downloads artifacts from ardessa/backend using GitHub API
  ↓
Extracts JSON files to /tmp/
```

**Step 3: Signal Processing (In-Memory)**
```
RuffParser.parse(ruff_report.json) → List[Signal]
MypyParser.parse(mypy_report.json) → List[Signal]  
BanditParser.parse(bandit_report.json) → List[Signal]
  ↓
Combine into single list: all_signals
```

**Step 4: Prioritization (In-Memory)**
```
SignalPrioritizer.prioritize_and_group(all_signals)
  ↓
Groups by:
  - Same signal type
  - Nearby location
  - Max 3 per group
  ↓
Sorts by priority (severity, file importance)
  ↓
Returns: List[SignalGroup]
```

**Step 5: Agent Processing (Sequential)**
```
For each SignalGroup (in priority order):
  ↓
  Get appropriate agent (LintAgent, TypeAgent, or SecurityAgent)
  ↓
  Agent.process(group):
    - Views file context
    - Generates fix with LLM
    - Validates with guardrails
    - Returns FixResult with changes
  ↓
  If successful: Add to pr_proposals list
```

**Step 6: PR Creation**
```
For each pr_proposal:
  ↓
  Create new branch in ardessa/backend
  ↓
  Commit changes
  ↓
  Open PR with:
    - Title: "Fix 3 lint issues in src/auth.py"
    - Body: Detailed explanation of fixes
    - Link back to CI run
  ↓
GitHub Actions completes and shuts down
```

---

## Configuration & Policy

**Literature basis**: AI-Augmented CI/CD Pipelines - policy-as-code guardrails

### Policy Configuration (YAML)
This is an exmaple how gaurdrails and configuration could be implemented as "Code" using a yaml file for settings

```yaml
# config/policies.yaml

ai_assistant:
  enabled: true
  max_prs_per_day: 5

  # From AI-Augmented CI/CD paper - trust levels
  trust_level: 1  # 0=observe, 1=propose, 2=auto-merge-low-risk, 3=full-autonomy

  confidence_thresholds:
    security: 0.95  # High confidence required for security fixes
    unit_test: 0.85
    integration: 0.85
    coverage: 0.75
    lint: 0.70

  signal_priorities:
    security:
      critical: 0  # Process immediately
      high: 1
      medium: 2
      low: 3

    unit_test:
      high: 1
      medium: 2
      low: 3

    integration:
      high: 1
      medium: 2

    coverage:
      medium: 2
      low: 3

    lint:
      low: 3

  validation_rules:
    # Always run tests before creating PR
    require_tests: true

    # Maximum iterations per fix attempt (from LLMLOOP)
    max_iterations: 3

    # Maximum files changed in single PR
    max_files_per_pr: 3

    # Require specific validations per signal type
    validations:
      security:
        - run_security_scan
        - run_unit_tests
        - run_integration_tests
      unit_test:
        - run_unit_tests
        - check_coverage
      integration:
        - run_integration_tests
        - run_unit_tests
      coverage:
        - run_unit_tests
        - measure_coverage
      lint:
        - run_linter

  pr_settings:
    # Auto-label PRs
    auto_label: true

    # Request review from specific teams
    review_teams:
      security: ["security-team"]
      integration: ["backend-team", "qa-team"]
      unit_test: ["dev-team"]

    # Enable draft PRs for low confidence fixes
    draft_on_low_confidence: true
    draft_threshold: 0.80
```

---

## Technology Stack

### Core Components
- **Language**: Python 3.11+
- **LLM Client**: OpenAI SDK (GPT-4) or Anthropic SDK (Claude 3.5)
- **Git Operations**: PyGithub or GitLab Python API
- **Queue**: Redis (for agent task queue)

### Integrations
- **CI/CD**: GitHub Actions, GitLab CI, Jenkins webhooks
- **Test Runners**: pytest, Jest, JUnit
- **Linters**: ESLint, Pylint, Ruff
- **Security Scanners**: Semgrep, Bandit, CodeQL
- **Coverage**: Coverage.py, Istanbul

---


---



## References

### Primary Sources

1. **Ravi, R., Bradshaw, D., Ruberto, S., Jahangirova, G., & Terragni, V. (2025)**. LLMLOOP: Improving LLM-Generated Code and Tests through Automated Iterative Feedback Loops. *ICSME 2025*.
   - **Used for**: Iterative feedback loop structure, validation approach, sequential processing

2. **Baqar, M., Naqvi, S., & Khanda, R. (2025)**. AI-Augmented CI/CD Pipelines: From Code Commit to Production with Autonomous Decisions.
   - **Used for**: Specialized agent pattern, policy boundaries, DORA metrics evaluation

3. **Zhang, Y., Ruan, H., Fan, Z., & Roychoudhury, A. (2024)**. AutoCodeRover: Autonomous Program Improvement. *ISSTA 2024*.
   - **Used for**: Tool-based agent interaction, finite state machine guidance, cost benchmarks

### Supporting Sources

4. **Abtahi, S. M., & Azim, A. (2025)**. Augmenting Large Language Models with Static Code Analysis for Automated Code Quality Improvements.
   - **Used for**: RAG integration, lint fix approach, direct vs LLM-based fixes

5. **Liu, Y., et al. (2024)**. MarsCode Agent: AI-native Automated Bug Fixing.
   - **Used for**: Multi-file fix approach, code knowledge graphs, dynamic vs static routing

6. **Khare, V., et al. (2025)**. DeputyDev - AI Powered Developer Assistant.
   - **Used for**: PR body format, context optimization, multi-agent reflection pattern

---

## Conclusion

This architecture provides a **simple, implementable foundation** for the Ardessa AI Code Assistant based on proven academic approaches:

- ✅ Uses off-the-shelf LLMs (GPT-4/Claude)
- ✅ Modular design (easy to build incrementally)
- ✅ Clear validation strategy (prevents bad PRs)
- ✅ Evidence-based (grounded in 3 primary papers)
- ✅ Production-focused (handles real CI/CD signals)

**Total estimated implementation time**: 10-12 weeks

**Next steps**:
1. Review architecture with thesis advisor
2. Begin Phase 1 implementation (Signal Collection)
3. Set up development environment
4. Validate with simple test cases

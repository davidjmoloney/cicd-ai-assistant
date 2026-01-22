"""
Local Regression Test Runner.

Runs the test suite locally against PR branches to verify fixes don't break existing functionality.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .test_case import RegressionResult


@dataclass
class RegressionConfig:
    """Configuration for regression test runner."""
    repo_path: str
    test_command: str = "pytest"
    test_args: list[str] = field(default_factory=lambda: ["-v", "--tb=short"])
    timeout: int = 600  # 10 minutes
    use_junit_xml: bool = True
    venv_path: Optional[str] = None
    github_token: Optional[str] = None
    remote_url: Optional[str] = None

    def __post_init__(self):
        if self.github_token is None:
            self.github_token = os.getenv("GITHUB_TOKEN", "")


class RegressionRunner:
    """
    Runs regression tests locally against PR branches.

    Workflow:
    1. Fetch the PR branch from remote
    2. Checkout the branch
    3. Run the test suite (pytest by default)
    4. Parse results (JUnit XML or exit code)
    5. Restore original branch

    Usage:
        runner = RegressionRunner(RegressionConfig(
            repo_path="/path/to/local/clone",
        ))
        result = runner.run_tests(branch="cicd-agent-fix/lint/20240101")
    """

    def __init__(self, config: RegressionConfig) -> None:
        """Initialize the runner."""
        self.config = config
        self.repo_path = Path(config.repo_path)

        if not self.repo_path.exists():
            raise ValueError(f"Repository path does not exist: {config.repo_path}")

    def run_tests(self, branch: str) -> RegressionResult:
        """
        Run regression tests on the specified branch.

        Args:
            branch: The branch name to test (e.g., PR branch)

        Returns:
            RegressionResult with test outcomes
        """
        original_branch = self._get_current_branch()

        try:
            # Fetch and checkout the branch
            fetch_success = self._fetch_branch(branch)
            if not fetch_success:
                return RegressionResult(
                    passed=0,
                    failed=0,
                    skipped=0,
                    errors=1,
                    total=0,
                    duration_seconds=0.0,
                    failure_details=[{"error": f"Failed to fetch branch: {branch}"}],
                )

            checkout_success = self._checkout_branch(branch)
            if not checkout_success:
                return RegressionResult(
                    passed=0,
                    failed=0,
                    skipped=0,
                    errors=1,
                    total=0,
                    duration_seconds=0.0,
                    failure_details=[{"error": f"Failed to checkout branch: {branch}"}],
                )

            # Run tests
            result = self._run_test_command()

            return result

        finally:
            # Restore original branch
            if original_branch:
                self._checkout_branch(original_branch)

    def run_tests_in_isolation(self, branch: str) -> RegressionResult:
        """
        Run tests in a fresh clone (isolated from the main repo).

        This is slower but ensures no local state affects the tests.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            clone_path = Path(tmpdir) / "repo"

            # Clone the repo
            clone_success = self._clone_repo(clone_path, branch)
            if not clone_success:
                return RegressionResult(
                    passed=0,
                    failed=0,
                    skipped=0,
                    errors=1,
                    total=0,
                    duration_seconds=0.0,
                    failure_details=[{"error": "Failed to clone repository"}],
                )

            # Run tests in the cloned repo
            original_path = self.repo_path
            self.repo_path = clone_path

            try:
                return self._run_test_command()
            finally:
                self.repo_path = original_path

    def _get_current_branch(self) -> Optional[str]:
        """Get the current branch name."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def _fetch_branch(self, branch: str) -> bool:
        """Fetch a branch from origin."""
        try:
            result = subprocess.run(
                ["git", "fetch", "origin", branch],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _checkout_branch(self, branch: str) -> bool:
        """Checkout a branch."""
        try:
            # First try direct checkout
            result = subprocess.run(
                ["git", "checkout", branch],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode == 0:
                return True

            # If that fails, try checking out from origin
            result = subprocess.run(
                ["git", "checkout", "-b", branch, f"origin/{branch}"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return result.returncode == 0

        except Exception:
            return False

    def _clone_repo(self, target_path: Path, branch: str) -> bool:
        """Clone the repository to a target path."""
        remote_url = self.config.remote_url
        if not remote_url:
            # Try to get remote URL from existing repo
            try:
                result = subprocess.run(
                    ["git", "config", "--get", "remote.origin.url"],
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    remote_url = result.stdout.strip()
            except Exception:
                pass

        if not remote_url:
            return False

        try:
            result = subprocess.run(
                ["git", "clone", "--branch", branch, "--depth", "1", remote_url, str(target_path)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _run_test_command(self) -> RegressionResult:
        """Run the test command and parse results."""
        import time

        start_time = time.time()

        # Build command
        cmd = [self.config.test_command] + list(self.config.test_args)

        # Add JUnit XML output if enabled
        junit_path = None
        if self.config.use_junit_xml:
            junit_path = self.repo_path / ".pytest_results.xml"
            cmd.extend(["--junitxml", str(junit_path)])

        # Set up environment
        env = os.environ.copy()
        if self.config.venv_path:
            venv_bin = Path(self.config.venv_path) / "bin"
            env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
            env["VIRTUAL_ENV"] = self.config.venv_path

        try:
            result = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=self.config.timeout,
                env=env,
            )

            duration = time.time() - start_time

            # Parse results
            if junit_path and junit_path.exists():
                return self._parse_junit_xml(junit_path, duration)
            else:
                return self._parse_exit_code(result, duration)

        except subprocess.TimeoutExpired:
            return RegressionResult(
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                total=0,
                duration_seconds=self.config.timeout,
                failure_details=[{"error": "Test command timed out"}],
            )
        except Exception as e:
            return RegressionResult(
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                total=0,
                duration_seconds=time.time() - start_time,
                failure_details=[{"error": str(e)}],
            )

    def _parse_junit_xml(self, xml_path: Path, duration: float) -> RegressionResult:
        """Parse JUnit XML test results."""
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            # Handle both testsuite and testsuites root elements
            if root.tag == "testsuites":
                testsuites = root.findall("testsuite")
            else:
                testsuites = [root]

            passed = 0
            failed = 0
            skipped = 0
            errors = 0
            failure_details = []

            for testsuite in testsuites:
                tests = int(testsuite.get("tests", 0))
                suite_failures = int(testsuite.get("failures", 0))
                suite_errors = int(testsuite.get("errors", 0))
                suite_skipped = int(testsuite.get("skipped", 0))

                failed += suite_failures
                errors += suite_errors
                skipped += suite_skipped
                passed += tests - suite_failures - suite_errors - suite_skipped

                # Collect failure details
                for testcase in testsuite.findall("testcase"):
                    failure = testcase.find("failure")
                    error = testcase.find("error")

                    if failure is not None:
                        failure_details.append({
                            "test": f"{testcase.get('classname', '')}.{testcase.get('name', '')}",
                            "type": "failure",
                            "message": failure.get("message", ""),
                            "text": failure.text or "",
                        })
                    elif error is not None:
                        failure_details.append({
                            "test": f"{testcase.get('classname', '')}.{testcase.get('name', '')}",
                            "type": "error",
                            "message": error.get("message", ""),
                            "text": error.text or "",
                        })

            return RegressionResult(
                passed=passed,
                failed=failed,
                skipped=skipped,
                errors=errors,
                total=passed + failed + skipped + errors,
                duration_seconds=duration,
                failure_details=failure_details,
            )

        except Exception as e:
            return RegressionResult(
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                total=0,
                duration_seconds=duration,
                failure_details=[{"error": f"Failed to parse JUnit XML: {e}"}],
            )

    def _parse_exit_code(self, result: subprocess.CompletedProcess, duration: float) -> RegressionResult:
        """
        Parse test results from exit code and output.

        This is a fallback when JUnit XML is not available.
        """
        # Try to extract test counts from pytest output
        # Common patterns: "X passed, Y failed, Z skipped"
        import re

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        output = stdout + stderr

        passed = 0
        failed = 0
        skipped = 0
        errors = 0

        # Match pytest summary line
        summary_match = re.search(
            r"(\d+)\s+passed.*?(\d+)\s+failed|(\d+)\s+passed",
            output,
            re.IGNORECASE,
        )

        if summary_match:
            groups = summary_match.groups()
            if groups[0]:
                passed = int(groups[0])
            if groups[1]:
                failed = int(groups[1])
            elif groups[2]:
                passed = int(groups[2])

        # Look for skipped
        skipped_match = re.search(r"(\d+)\s+skipped", output, re.IGNORECASE)
        if skipped_match:
            skipped = int(skipped_match.group(1))

        # Look for errors
        error_match = re.search(r"(\d+)\s+error", output, re.IGNORECASE)
        if error_match:
            errors = int(error_match.group(1))

        # If we couldn't parse anything, use exit code
        if passed == 0 and failed == 0 and result.returncode != 0:
            failed = 1

        failure_details = []
        if result.returncode != 0:
            failure_details.append({
                "error": f"Exit code: {result.returncode}",
                "stdout": stdout[-1000:] if len(stdout) > 1000 else stdout,
                "stderr": stderr[-1000:] if len(stderr) > 1000 else stderr,
            })

        return RegressionResult(
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=errors,
            total=passed + failed + skipped + errors,
            duration_seconds=duration,
            failure_details=failure_details,
        )


class CICDToolRunner:
    """
    Runs CICD tools (ruff, mypy, bandit) to verify fixes resolved the errors.

    This is complementary to regression tests - it verifies the specific
    error being fixed is actually resolved.
    """

    def __init__(self, repo_path: str) -> None:
        """Initialize the runner."""
        self.repo_path = Path(repo_path)

    def verify_ruff_fix(self, file_path: str, error_code: str) -> dict:
        """
        Verify a ruff error is fixed in a specific file.

        Returns:
            {"resolved": bool, "remaining_errors": list}
        """
        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format=json", file_path],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0:
                # No errors
                return {"resolved": True, "remaining_errors": []}

            errors = json.loads(result.stdout) if result.stdout else []
            matching_errors = [e for e in errors if e.get("code") == error_code]

            return {
                "resolved": len(matching_errors) == 0,
                "remaining_errors": matching_errors,
            }

        except Exception as e:
            return {"resolved": False, "error": str(e)}

    def verify_mypy_fix(self, file_path: str, error_code: str) -> dict:
        """
        Verify a mypy error is fixed in a specific file.

        Returns:
            {"resolved": bool, "remaining_errors": list}
        """
        try:
            result = subprocess.run(
                ["mypy", "--output=json", file_path],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0:
                return {"resolved": True, "remaining_errors": []}

            # Parse newline-delimited JSON
            errors = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    try:
                        errors.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

            matching_errors = [e for e in errors if e.get("code") == error_code]

            return {
                "resolved": len(matching_errors) == 0,
                "remaining_errors": matching_errors,
            }

        except Exception as e:
            return {"resolved": False, "error": str(e)}

    def run_all_cicd_tools(self) -> dict:
        """
        Run all CICD tools and return aggregated results.

        Useful for baseline measurement before/after fixes.
        """
        results = {}

        # Ruff
        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format=json", "."],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            errors = json.loads(result.stdout) if result.stdout else []
            results["ruff"] = {
                "error_count": len(errors),
                "errors": errors[:10],  # First 10 only
            }
        except Exception as e:
            results["ruff"] = {"error": str(e)}

        # MyPy
        try:
            result = subprocess.run(
                ["mypy", "--output=json", "."],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=300,
            )
            errors = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    try:
                        errors.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            results["mypy"] = {
                "error_count": len(errors),
                "errors": errors[:10],
            }
        except Exception as e:
            results["mypy"] = {"error": str(e)}

        return results

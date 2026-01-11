"""Shared test configuration for all test scripts."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestConfig:
    """Global test configuration loaded from environment variables."""

    # Test mode
    make_llm_call: bool = field(
        default_factory=lambda: os.getenv("MAKE_LLM_CALL", "false").lower() in ("true", "1", "yes")
    )

    # Paths
    repo_root: Path = field(default_factory=lambda: Path(__file__).parent.parent.parent)

    @property
    def src_dir(self) -> Path:
        """Source directory containing the main codebase."""
        return self.repo_root / "src"

    @property
    def scripts_dir(self) -> Path:
        """Scripts directory."""
        return self.repo_root / "scripts"

    @property
    def common_dir(self) -> Path:
        """Common scripts directory."""
        return self.scripts_dir / "common"

    @property
    def tests_dir(self) -> Path:
        """Tests directory."""
        return self.scripts_dir / "tests"

    @property
    def debug_dir(self) -> Path:
        """Debug scripts directory."""
        return self.scripts_dir / "debug"

    @property
    def debug_output_dir(self) -> Path:
        """Debug output directory."""
        return self.debug_dir / "outputs"

    @property
    def sample_artifacts_dir(self) -> Path:
        """Sample CI/CD artifacts directory."""
        return self.repo_root / "sample-cicd-artifacts"

    # Target repository (for integration tests)
    target_repo_root: str = field(
        default_factory=lambda: os.getenv("TARGET_REPO_ROOT", "/home/devel/ardessa-agent")
    )

    # API Keys
    openai_api_key: str = field(
        default_factory=lambda: os.getenv("OPENAI_API_KEY", "").strip()
    )

    anthropic_api_key: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "").strip()
    )

    github_token: str = field(
        default_factory=lambda: os.getenv("GITHUB_TOKEN", "").strip()
    )

    # GitHub configuration
    target_repo_owner: str = field(
        default_factory=lambda: os.getenv("TARGET_REPO_OWNER", "").strip()
    )

    target_repo_name: str = field(
        default_factory=lambda: os.getenv("TARGET_REPO_NAME", "").strip()
    )

    target_repo_default_branch: str = field(
        default_factory=lambda: os.getenv("TARGET_REPO_DEFAULT_BRANCH", "main").strip()
    )

    def validate(self) -> list[str]:
        """
        Validate configuration and return list of errors.

        Returns:
            List of validation error messages. Empty list if valid.
        """
        errors = []

        # Check for API keys when in live mode
        if self.make_llm_call:
            if not self.openai_api_key and not self.anthropic_api_key:
                errors.append(
                    "OPENAI_API_KEY or ANTHROPIC_API_KEY not set "
                    "(required for MAKE_LLM_CALL=true)"
                )

        # Check for required directories
        if not self.src_dir.exists():
            errors.append(f"Source directory not found: {self.src_dir}")

        if not self.sample_artifacts_dir.exists():
            errors.append(
                f"Sample artifacts directory not found: {self.sample_artifacts_dir}"
            )

        return errors

    def print_summary(self) -> None:
        """Print configuration summary."""
        print("Test Configuration:")
        print(f"  Mode: {'LIVE (making API calls)' if self.make_llm_call else 'FIXTURE (using cached data)'}")
        print(f"  Repo root: {self.repo_root}")
        print(f"  Source dir: {self.src_dir}")
        print(f"  Target repo: {self.target_repo_root}")

        if self.make_llm_call:
            print(f"  OpenAI API key: {'✓ set' if self.openai_api_key else '✗ not set'}")
            print(f"  Anthropic API key: {'✓ set' if self.anthropic_api_key else '✗ not set'}")

        # Validate and print errors
        errors = self.validate()
        if errors:
            print("\nConfiguration errors:")
            for error in errors:
                print(f"  ✗ {error}")

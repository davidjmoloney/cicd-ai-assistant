# github/client.py
"""
Shared GitHub API utilities for CI/CD AI Assistant.

Provides reusable HTTP helpers, authentication, and file-reading
functions used by both PRGenerator and ContextBuilder.

Configuration via environment variables:
    GITHUB_TOKEN               - GitHub PAT with repo permissions
    TARGET_REPO_OWNER          - Owner of target repository (e.g., "my-org")
    TARGET_REPO_NAME           - Name of target repository (e.g., "backend")
    TARGET_REPO_DEFAULT_BRANCH - Branch to create PRs against (default: "main")
"""
from __future__ import annotations

import base64
import os
import time
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Configuration
# =============================================================================

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
TARGET_REPO_OWNER = os.getenv("TARGET_REPO_OWNER", "").strip()
TARGET_REPO_NAME = os.getenv("TARGET_REPO_NAME", "").strip()
TARGET_REPO_DEFAULT_BRANCH = os.getenv("TARGET_REPO_DEFAULT_BRANCH", "main").strip()

# API constants
GITHUB_API_URL = "https://api.github.com"
MAX_RETRIES = 4
RETRY_DELAYS = [2, 4, 8, 16]


# =============================================================================
# Exceptions
# =============================================================================

class GitHubError(Exception):
    """GitHub API error."""
    pass


# =============================================================================
# HTTP Helpers
# =============================================================================

def github_headers() -> dict[str, str]:
    """Get headers for GitHub API requests."""
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_request(
    client: httpx.Client,
    method: str,
    path: str,
    json_data: Optional[dict] = None,
) -> dict[str, Any]:
    """Make a GitHub API request with retry logic."""
    url = f"{GITHUB_API_URL}{path}"

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.request(method, url, json=json_data)

            if response.status_code in (200, 201):
                return response.json()
            elif response.status_code == 422:
                error = response.json()
                raise GitHubError(f"Validation error: {error.get('message', 'Unknown')}")
            elif response.status_code >= 500 and attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt])
                continue
            else:
                error = response.json() if response.content else {}
                raise GitHubError(f"API error {response.status_code}: {error.get('message', 'Unknown')}")

        except httpx.RequestError as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAYS[attempt])
                continue
            raise GitHubError(f"Network error: {e}")

    raise GitHubError("Max retries exceeded")


# =============================================================================
# File Reading
# =============================================================================

def read_file_from_github(
    client: httpx.Client,
    owner: str,
    repo: str,
    file_path: str,
    ref: str,
) -> str:
    """Read a file's content from the GitHub Contents API.

    Args:
        client: httpx.Client with GitHub auth headers.
        owner: Repository owner.
        repo: Repository name.
        file_path: Repo-relative file path.
        ref: Branch name or commit SHA to read from.

    Returns:
        Decoded UTF-8 string of the file content.

    Raises:
        GitHubError: On API or network errors.
    """
    data = github_request(
        client, "GET",
        f"/repos/{owner}/{repo}/contents/{file_path}?ref={ref}",
    )
    return base64.b64decode(data["content"]).decode("utf-8")

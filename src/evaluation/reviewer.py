"""
GitHub Copilot Review Integration.

Requests and processes code reviews from GitHub Copilot for PRs.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import httpx

from .test_case import ReviewResult, ReviewVerdict


# GitHub API constants
GITHUB_API_URL = "https://api.github.com"
MAX_RETRIES = 4
RETRY_DELAYS = [2, 4, 8, 16]
REVIEW_POLL_INTERVAL = 10  # seconds
REVIEW_TIMEOUT = 300  # seconds (5 minutes)


@dataclass
class ReviewerConfig:
    """Configuration for the reviewer."""
    repo_owner: str
    repo_name: str
    github_token: Optional[str] = None
    poll_interval: int = REVIEW_POLL_INTERVAL
    timeout: int = REVIEW_TIMEOUT

    def __post_init__(self):
        if self.github_token is None:
            self.github_token = os.getenv("GITHUB_TOKEN", "")


class CopilotReviewer:
    """
    Integrates with GitHub Copilot for PR code reviews.

    GitHub Copilot can review PRs when requested. This class:
    1. Requests a Copilot review on a PR
    2. Polls for review completion
    3. Extracts the review verdict and feedback

    Usage:
        reviewer = CopilotReviewer(ReviewerConfig(
            repo_owner="my-org",
            repo_name="my-repo",
        ))
        result = reviewer.request_review(pr_number=123)

    Note: GitHub Copilot reviews require:
    - GitHub Copilot Enterprise or Copilot for Business
    - Copilot code review enabled for the repository
    """

    # The GitHub username for Copilot reviews
    COPILOT_USERNAME = "copilot"

    def __init__(self, config: ReviewerConfig) -> None:
        """Initialize the reviewer."""
        self.config = config
        if not config.github_token:
            raise ValueError("GITHUB_TOKEN is required for reviews")

    def _headers(self) -> dict[str, str]:
        """Get headers for GitHub API requests."""
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.config.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _api_request(
        self,
        client: httpx.Client,
        method: str,
        path: str,
        json_data: Optional[dict] = None,
    ) -> dict:
        """Make a GitHub API request with retry logic."""
        url = f"{GITHUB_API_URL}{path}"

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = client.request(method, url, json=json_data)

                if response.status_code in (200, 201):
                    return response.json()
                elif response.status_code == 404:
                    return {"error": "not_found"}
                elif response.status_code == 422:
                    error = response.json()
                    return {"error": f"validation_error: {error.get('message', 'Unknown')}"}
                elif response.status_code >= 500 and attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAYS[attempt])
                    continue
                else:
                    error = response.json() if response.content else {}
                    return {"error": f"api_error_{response.status_code}: {error.get('message', 'Unknown')}"}

            except httpx.RequestError as e:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAYS[attempt])
                    continue
                return {"error": f"network_error: {e}"}

        return {"error": "max_retries_exceeded"}

    def request_review(self, pr_number: int) -> ReviewResult:
        """
        Request a GitHub Copilot review on a PR and wait for completion.

        Args:
            pr_number: The PR number to review

        Returns:
            ReviewResult with verdict and feedback
        """
        owner = self.config.repo_owner
        repo = self.config.repo_name

        with httpx.Client(headers=self._headers(), timeout=30.0) as client:
            # Step 1: Request review from Copilot
            request_result = self._request_copilot_review(client, owner, repo, pr_number)
            if "error" in request_result:
                return ReviewResult(
                    verdict=ReviewVerdict.ERROR,
                    reviewer=self.COPILOT_USERNAME,
                    feedback=f"Failed to request review: {request_result['error']}",
                )

            # Step 2: Poll for review completion
            review = self._poll_for_review(client, owner, repo, pr_number)
            if review is None:
                return ReviewResult(
                    verdict=ReviewVerdict.PENDING,
                    reviewer=self.COPILOT_USERNAME,
                    feedback="Review timed out",
                )

            # Step 3: Parse review result
            return self._parse_review(review)

    def _request_copilot_review(
        self,
        client: httpx.Client,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> dict:
        """
        Request a review from GitHub Copilot.

        Uses the GitHub API to request a review from the 'copilot' user.
        """
        path = f"/repos/{owner}/{repo}/pulls/{pr_number}/requested_reviewers"

        # Request review from Copilot
        result = self._api_request(client, "POST", path, {
            "reviewers": [self.COPILOT_USERNAME],
        })

        return result

    def _poll_for_review(
        self,
        client: httpx.Client,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> Optional[dict]:
        """
        Poll for a completed review from Copilot.

        Returns the review data if found, None if timeout.
        """
        path = f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        start_time = time.time()

        while (time.time() - start_time) < self.config.timeout:
            result = self._api_request(client, "GET", path)

            if "error" in result:
                time.sleep(self.config.poll_interval)
                continue

            # Look for Copilot's review
            reviews = result if isinstance(result, list) else []
            for review in reviews:
                if review.get("user", {}).get("login") == self.COPILOT_USERNAME:
                    state = review.get("state", "")
                    # Check if review is complete (not PENDING)
                    if state in ("APPROVED", "CHANGES_REQUESTED", "COMMENTED"):
                        return review

            time.sleep(self.config.poll_interval)

        return None

    def _parse_review(self, review: dict) -> ReviewResult:
        """Parse a GitHub review into ReviewResult."""
        state = review.get("state", "PENDING")
        body = review.get("body", "")

        # Map GitHub review states to our verdicts
        verdict_map = {
            "APPROVED": ReviewVerdict.APPROVED,
            "CHANGES_REQUESTED": ReviewVerdict.CHANGES_REQUESTED,
            "COMMENTED": ReviewVerdict.COMMENTED,
            "PENDING": ReviewVerdict.PENDING,
        }
        verdict = verdict_map.get(state, ReviewVerdict.PENDING)

        # Try to extract a quality score from the review body
        # Copilot reviews may include structured feedback
        quality_score = self._extract_quality_score(body)

        return ReviewResult(
            verdict=verdict,
            reviewer=self.COPILOT_USERNAME,
            feedback=body,
            quality_score=quality_score,
            review_url=review.get("html_url"),
            reviewed_at=datetime.fromisoformat(
                review.get("submitted_at", "").replace("Z", "+00:00")
            ) if review.get("submitted_at") else None,
        )

    def _extract_quality_score(self, body: str) -> Optional[int]:
        """
        Try to extract a quality score from the review body.

        Returns 1-5 if found, None otherwise.
        """
        # This is a placeholder - actual Copilot reviews may have
        # different formats. Adjust based on actual output.
        import re

        # Look for patterns like "Score: 4/5" or "Quality: 3"
        patterns = [
            r"[Ss]core:\s*(\d)/5",
            r"[Qq]uality:\s*(\d)",
            r"(\d)/5",
        ]

        for pattern in patterns:
            match = re.search(pattern, body)
            if match:
                score = int(match.group(1))
                if 1 <= score <= 5:
                    return score

        return None

    def get_review_status(self, pr_number: int) -> str:
        """
        Get the current review status for a PR without waiting.

        Returns one of: "pending", "approved", "changes_requested", "commented", "none"
        """
        owner = self.config.repo_owner
        repo = self.config.repo_name

        with httpx.Client(headers=self._headers(), timeout=30.0) as client:
            path = f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
            result = self._api_request(client, "GET", path)

            if "error" in result:
                return "error"

            reviews = result if isinstance(result, list) else []
            for review in reviews:
                if review.get("user", {}).get("login") == self.COPILOT_USERNAME:
                    state = review.get("state", "PENDING").lower()
                    if state == "changes_requested":
                        return "changes_requested"
                    return state

            return "none"


class ManualReviewer:
    """
    Fallback reviewer that uses manual or alternative review mechanisms.

    This can be used when Copilot is not available, or for comparing
    Copilot reviews against other review methods (e.g., human review,
    other AI tools).
    """

    def __init__(self, reviewer_name: str = "manual") -> None:
        self.reviewer_name = reviewer_name

    def create_pending_review(self, pr_url: str) -> ReviewResult:
        """
        Create a pending review result for manual follow-up.

        Args:
            pr_url: URL of the PR to review

        Returns:
            ReviewResult marked as pending
        """
        return ReviewResult(
            verdict=ReviewVerdict.PENDING,
            reviewer=self.reviewer_name,
            feedback=f"Manual review required: {pr_url}",
            review_url=pr_url,
        )

    def record_manual_review(
        self,
        verdict: str,
        feedback: str,
        quality_score: Optional[int] = None,
    ) -> ReviewResult:
        """
        Record a manual review result.

        Args:
            verdict: "approved", "changes_requested", or "commented"
            feedback: Review feedback text
            quality_score: Optional 1-5 quality rating

        Returns:
            ReviewResult with the provided information
        """
        verdict_map = {
            "approved": ReviewVerdict.APPROVED,
            "changes_requested": ReviewVerdict.CHANGES_REQUESTED,
            "commented": ReviewVerdict.COMMENTED,
        }

        return ReviewResult(
            verdict=verdict_map.get(verdict.lower(), ReviewVerdict.COMMENTED),
            reviewer=self.reviewer_name,
            feedback=feedback,
            quality_score=quality_score,
            reviewed_at=datetime.now(),
        )

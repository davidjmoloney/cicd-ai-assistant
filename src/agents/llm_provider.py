# agents/llm_provider.py
"""
LLM Provider abstraction layer.

This module provides a single boundary for all LLM-specific code.
Swap providers by changing the provider instance - no need to modify
other parts of the codebase.

Configuration:
    Set API keys via environment variables or hardcode them below.
    - OPENAI_API_KEY: OpenAI API key
    - ANTHROPIC_API_KEY: Anthropic API key
"""
from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from dotenv import load_dotenv


# ============================================================================
# Configuration
# ============================================================================

# Fine for an app entrypoint. If this module is imported by tooling/tests,
# consider moving load_dotenv() into your main() instead.
load_dotenv()

OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL: str = os.environ.get("OPENAI_MODEL", "gpt-4o").strip()
OPENAI_API_URL: str = os.environ.get("OPENAI_API_URL", "https://api.openai.com/v1/responses").strip()

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514").strip()
ANTHROPIC_API_URL: str = os.environ.get("ANTHROPIC_API_URL","https://api.anthropic.com/v1/messages").strip()
ANTHROPIC_API_VERSION: str = "2023-06-01"


# ============================================================================
# Response types
# ============================================================================

@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str
    model: str
    usage: dict[str, int]  # tokens used
    raw_response: dict[str, Any]  # full API response for debugging


@dataclass
class LLMError:
    """Error response from LLM provider."""
    error_type: str
    message: str
    status_code: Optional[int] = None
    raw_response: Optional[dict[str, Any]] = None


# ============================================================================
# Abstract base provider
# ============================================================================

class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    All provider-specific code is contained within provider implementations.
    The rest of the codebase only interacts with this interface.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name (e.g., 'openai', 'anthropic')."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model being used."""
        ...

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: Optional[dict[str, Any]] = None,
    ) -> LLMResponse | LLMError:
        """
        Generate a completion from the LLM.

        Args:
            system_prompt: System instructions for the model
            user_prompt: User message/context
            temperature: Sampling temperature (0.0 = deterministic)
            max_tokens: Maximum tokens in response
            response_format: Optional JSON schema for structured output

        Returns:
            LLMResponse on success, LLMError on failure
        """
        ...

    def is_configured(self) -> bool:
        """Check if the provider has valid configuration (API key set)."""
        return True


# ============================================================================
# OpenAI Provider
# ============================================================================

class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_url: Optional[str] = None,
        timeout_s: float = 120.0,
        max_retries: int = 4,
    ) -> None:
        self._api_key = (api_key or OPENAI_API_KEY).strip()
        self._model = (model or OPENAI_MODEL).strip()
        self._api_url = (api_url or OPENAI_API_URL).strip()
        self._timeout_s = timeout_s
        self._max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float,
        max_tokens: int,
        response_format: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        # Responses API uses `input` and `max_output_tokens`
        payload: dict[str, Any] = {
            "model": self._model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        # If you want JSON output, you typically do it via `response_format`.
        # Exact schema depends on your needs; keep as passthrough.
        if response_format is not None:
            payload["response_format"] = response_format

        return payload

    def _extract_text(self, data: dict[str, Any]) -> str:
        """
        Responses API output can be structured; extract best-effort text.
        """
        # Common: data["output"][...]["content"][...]["text"]
        output = data.get("output", [])
        chunks: list[str] = []
        for item in output:
            for c in item.get("content", []) or []:
                if isinstance(c, dict) and c.get("type") == "output_text":
                    chunks.append(c.get("text", ""))
                elif isinstance(c, dict) and "text" in c:
                    chunks.append(str(c["text"]))
        if chunks:
            return "".join(chunks).strip()

        # Fallbacks (be defensive)
        if "text" in data:
            return str(data["text"]).strip()
        return ""

    def _usage(self, data: dict[str, Any]) -> dict[str, int]:
        usage = data.get("usage") or {}
        # Responses may expose input/output tokens
        return {
            "prompt_tokens": int(usage.get("input_tokens", 0)),
            "completion_tokens": int(usage.get("output_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
        }

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        response_format: Optional[dict[str, Any]] = None,
    ) -> LLMResponse | LLMError:
        if not self.is_configured():
            return LLMError(
                error_type="configuration_error",
                message="OPENAI_API_KEY is missing or empty. Check your .env and environment.",
            )

        payload = self._build_payload(
            system_prompt,
            user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                for attempt in range(self._max_retries + 1):
                    resp = client.post(self._api_url, headers=self._headers(), json=payload)

                    if resp.status_code == 200:
                        data = resp.json()
                        content = self._extract_text(data)
                        return LLMResponse(
                            content=content,
                            model=data.get("model", self._model),
                            usage=self._usage(data),
                            raw_response=data,
                        )

                    # Retry policy: only for 429/5xx, otherwise fail fast
                    retryable = resp.status_code in (429, 500, 502, 503, 504)

                    raw = None
                    try:
                        raw = resp.json() if resp.content else None
                    except Exception:
                        raw = {"text": resp.text} if resp.text else None

                    if not retryable or attempt >= self._max_retries:
                        return LLMError(
                            error_type="api_error",
                            message=f"OpenAI API returned status {resp.status_code}",
                            status_code=resp.status_code,
                            raw_response=raw,
                        )

                    # Backoff. Respect Retry-After if supplied.
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after is not None:
                        try:
                            sleep_s = max(0.0, float(retry_after))
                        except ValueError:
                            sleep_s = 2 ** attempt
                    else:
                        sleep_s = 2 ** attempt  # 1,2,4,8...

                    time.sleep(min(sleep_s, 30.0))

        except httpx.TimeoutException:
            return LLMError(error_type="timeout", message="OpenAI API request timed out")
        except Exception as e:
            return LLMError(error_type="unknown", message=str(e))
        


# ============================================================================
# Claude/Anthropic Provider (minimal)
# ============================================================================

class ClaudeProvider(LLMProvider):
    """Anthropic Claude API provider (Messages API)."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_url: Optional[str] = None,
        api_version: Optional[str] = None,
        timeout_s: float = 120.0,
        max_retries: int = 4,
    ) -> None:
        self._api_key = (api_key or ANTHROPIC_API_KEY).strip()
        self._model = (model or ANTHROPIC_MODEL).strip()
        self._api_url = (api_url or ANTHROPIC_API_URL).strip()
        self._api_version = (api_version or ANTHROPIC_API_VERSION).strip()
        self._timeout_s = timeout_s
        self._max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": self._api_version,
            "content-type": "application/json",
        }

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    def _extract_text(self, data: dict[str, Any]) -> str:
        # Claude returns content as a list of blocks: [{"type":"text","text":"..."}]
        blocks = data.get("content") or []
        chunks: list[str] = []
        for b in blocks:
            if isinstance(b, dict) and b.get("type") == "text":
                chunks.append(b.get("text", ""))
        return "".join(chunks).strip()

    def _usage(self, data: dict[str, Any]) -> dict[str, int]:
        usage = data.get("usage") or {}
        in_tok = int(usage.get("input_tokens", 0))
        out_tok = int(usage.get("output_tokens", 0))
        return {
            "prompt_tokens": in_tok,
            "completion_tokens": out_tok,
            "total_tokens": in_tok + out_tok,
        }

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: Optional[dict[str, Any]] = None,  # kept for interface compatibility; ignored
    ) -> LLMResponse | LLMError:
        if not self.is_configured():
            return LLMError(
                error_type="configuration_error",
                message="ANTHROPIC_API_KEY is missing or empty. Check your .env and environment.",
            )

        payload = self._build_payload(
            system_prompt,
            user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        try:
            with httpx.Client(timeout=self._timeout_s) as client:
                for attempt in range(self._max_retries + 1):
                    resp = client.post(self._api_url, headers=self._headers(), json=payload)

                    if resp.status_code == 200:
                        data = resp.json()
                        return LLMResponse(
                            content=self._extract_text(data),
                            model=data.get("model", self._model),
                            usage=self._usage(data),
                            raw_response=data,
                        )

                    retryable = resp.status_code in (429, 500, 502, 503, 504)

                    raw = None
                    try:
                        raw = resp.json() if resp.content else None
                    except Exception:
                        raw = {"text": resp.text} if resp.text else None

                    if not retryable or attempt >= self._max_retries:
                        return LLMError(
                            error_type="api_error",
                            message=f"Anthropic API returned status {resp.status_code}",
                            status_code=resp.status_code,
                            raw_response=raw,
                        )

                    retry_after = resp.headers.get("Retry-After")
                    if retry_after is not None:
                        try:
                            sleep_s = max(0.0, float(retry_after))
                        except ValueError:
                            sleep_s = 2 ** attempt
                    else:
                        sleep_s = 2 ** attempt

                    time.sleep(min(sleep_s, 30.0))

        except httpx.TimeoutException:
            return LLMError(error_type="timeout", message="Anthropic API request timed out")
        except Exception as e:
            return LLMError(error_type="unknown", message=str(e))


# ============================================================================
# Provider factory
# ============================================================================

def get_provider(provider_name: str = "openai", **kwargs: Any) -> LLMProvider:
    """
    Factory function to get a provider instance.

    Args:
        provider_name: 'openai' or 'anthropic' (or 'claude')
        **kwargs: Provider-specific configuration

    Returns:
        Configured LLMProvider instance
    """
    name = provider_name.lower()

    if name == "openai":
        return OpenAIProvider(**kwargs)
    elif name in ("anthropic", "claude"):
        return ClaudeProvider(**kwargs)
    else:
        raise ValueError(f"Unknown provider: {provider_name}. Use 'openai' or 'anthropic'.")

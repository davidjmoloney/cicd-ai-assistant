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

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import httpx


# ============================================================================
# Configuration (single place to set API keys/endpoints)
# ============================================================================

# Hardcode keys here for testing, or use environment variables
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL: str = "gpt-4o"
OPENAI_API_URL: str = "https://api.openai.com/v1/chat/completions"

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"
ANTHROPIC_API_URL: str = "https://api.anthropic.com/v1/messages"
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
    """OpenAI API provider (GPT-4, etc.)."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_url: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or OPENAI_API_KEY
        self._model = model or OPENAI_MODEL
        self._api_url = api_url or OPENAI_API_URL

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: Optional[dict[str, Any]] = None,
    ) -> LLMResponse | LLMError:
        if not self.is_configured():
            return LLMError(
                error_type="configuration_error",
                message="OpenAI API key not configured",
            )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Add JSON mode if requested
        if response_format is not None:
            payload["response_format"] = response_format

        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(self._api_url, headers=headers, json=payload)

            if response.status_code != 200:
                return LLMError(
                    error_type="api_error",
                    message=f"OpenAI API returned status {response.status_code}",
                    status_code=response.status_code,
                    raw_response=response.json() if response.content else None,
                )

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            return LLMResponse(
                content=content,
                model=data.get("model", self._model),
                usage={
                    "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
                    "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                    "total_tokens": data.get("usage", {}).get("total_tokens", 0),
                },
                raw_response=data,
            )

        except httpx.TimeoutException:
            return LLMError(
                error_type="timeout",
                message="OpenAI API request timed out",
            )
        except Exception as e:
            return LLMError(
                error_type="unknown",
                message=str(e),
            )


# ============================================================================
# Claude/Anthropic Provider
# ============================================================================

class ClaudeProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_url: Optional[str] = None,
        api_version: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or ANTHROPIC_API_KEY
        self._model = model or ANTHROPIC_MODEL
        self._api_url = api_url or ANTHROPIC_API_URL
        self._api_version = api_version or ANTHROPIC_API_VERSION

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        response_format: Optional[dict[str, Any]] = None,
    ) -> LLMResponse | LLMError:
        if not self.is_configured():
            return LLMError(
                error_type="configuration_error",
                message="Anthropic API key not configured",
            )

        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self._api_version,
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self._model,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            with httpx.Client(timeout=120.0) as client:
                response = client.post(self._api_url, headers=headers, json=payload)

            if response.status_code != 200:
                return LLMError(
                    error_type="api_error",
                    message=f"Anthropic API returned status {response.status_code}",
                    status_code=response.status_code,
                    raw_response=response.json() if response.content else None,
                )

            data = response.json()

            # Claude returns content as a list of content blocks
            content_blocks = data.get("content", [])
            content = ""
            for block in content_blocks:
                if block.get("type") == "text":
                    content += block.get("text", "")

            return LLMResponse(
                content=content,
                model=data.get("model", self._model),
                usage={
                    "prompt_tokens": data.get("usage", {}).get("input_tokens", 0),
                    "completion_tokens": data.get("usage", {}).get("output_tokens", 0),
                    "total_tokens": (
                        data.get("usage", {}).get("input_tokens", 0)
                        + data.get("usage", {}).get("output_tokens", 0)
                    ),
                },
                raw_response=data,
            )

        except httpx.TimeoutException:
            return LLMError(
                error_type="timeout",
                message="Anthropic API request timed out",
            )
        except Exception as e:
            return LLMError(
                error_type="unknown",
                message=str(e),
            )


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

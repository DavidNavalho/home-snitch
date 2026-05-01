"""Optional chat provider clients for generated Ask answers."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from homewiki.config import ChatSettings, Settings


class ChatConfigurationError(ValueError):
    """Raised when the selected chat provider is missing required settings."""


class ChatProviderError(RuntimeError):
    """Raised when a chat provider request fails or returns malformed data."""


class ChatClient(Protocol):
    """Small provider-neutral chat interface used by Ask service."""

    provider: str

    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return answer text for OpenAI-compatible chat messages."""


@dataclass(frozen=True)
class OpenAICompatibleChatClient:
    """HTTP client for OpenAI-compatible /chat/completions endpoints."""

    api_base: str
    api_key: str
    model: str
    provider: str = "openai_compatible"

    def complete(self, messages: list[dict[str, str]]) -> str:
        endpoint = f"{self.api_base.rstrip('/')}/chat/completions"
        payload = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "temperature": 0,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ChatProviderError(
                "openai_compatible chat request failed "
                f"for model {self.model!r}: HTTP {exc.code} {detail}"
            ) from exc
        except OSError as exc:
            raise ChatProviderError(
                "openai_compatible chat request failed "
                f"for model {self.model!r} at {endpoint!r}: {exc}"
            ) from exc

        try:
            data = json.loads(body.decode("utf-8"))
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ChatProviderError(
                "openai_compatible chat response did not match the "
                "OpenAI chat completions schema"
            ) from exc

        if not isinstance(answer, str) or not answer.strip():
            raise ChatProviderError("openai_compatible chat response was empty")
        return answer.strip()


def create_chat_client(settings: Settings | ChatSettings) -> ChatClient | None:
    """Create the configured chat provider, or None when chat is disabled."""

    chat = settings.chat if isinstance(settings, Settings) else settings

    if chat.provider == "disabled":
        return None

    if chat.provider == "openai_compatible":
        _require_non_blank(
            {
                "CHAT_API_BASE": chat.api_base,
                "CHAT_MODEL": chat.model,
            },
            provider=chat.provider,
        )
        return OpenAICompatibleChatClient(
            api_base=chat.api_base,
            api_key=chat.api_key,
            model=chat.model,
        )

    raise ChatConfigurationError(f"Unsupported chat provider: {chat.provider!r}")


def _require_non_blank(values: dict[str, str], *, provider: str) -> None:
    missing = [name for name, value in values.items() if not value.strip()]
    if missing:
        joined = ", ".join(missing)
        raise ChatConfigurationError(
            f"Missing chat configuration for {provider}: {joined}"
        )


__all__ = [
    "ChatClient",
    "ChatConfigurationError",
    "ChatProviderError",
    "OpenAICompatibleChatClient",
    "create_chat_client",
]

"""Optional chat provider clients for generated Ask answers."""

from __future__ import annotations

import json
import subprocess
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
    timeout_seconds: int = 60

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
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
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


@dataclass(frozen=True)
class CodexChatClient:
    """Client that runs local Codex CLI with evidence prompt."""

    command: str
    model: str = ""
    timeout_seconds: int = 120
    workdir: str = ""
    output_schema: str = ""
    provider: str = "codex_cli"

    def complete(self, messages: list[dict[str, str]]) -> str:
        prompt = _render_messages_as_prompt(messages)
        command = [
            self.command,
            "exec",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--skip-git-repo-check",
            "--json",
        ]
        if self.workdir:
            command.extend(["--cd", self.workdir])
        if self.model:
            command.extend(["-m", self.model])
        if self.output_schema:
            command.extend(["--output-schema", self.output_schema])
        command.append("-")

        if not self.command.strip():
            raise ChatProviderError("Codex command is missing")

        try:
            completed = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except OSError as exc:
            raise ChatProviderError(
                "Failed to execute codex command "
                f"{self.command!r}: {exc}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ChatProviderError(
                f"Codex command timed out after {self.timeout_seconds} seconds"
            ) from exc

        if completed.returncode != 0:
            error = (completed.stderr or "").strip() or "(no stderr)"
            raise ChatProviderError(
                f"Codex command failed with exit {completed.returncode}: {error}"
            )

        output = (completed.stdout or "").strip()
        if not output:
            raise ChatProviderError("Codex command returned empty output")

        answer = _extract_text_response(output)
        if not answer:
            raise ChatProviderError(
                "Codex command output was empty after response extraction"
            )
        return answer


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
            timeout_seconds=max(1, chat.chat_timeout_seconds),
        )

    if chat.provider == "lmstudio_openai":
        _require_non_blank(
            {
                "LMSTUDIO_API_BASE": chat.lmstudio_api_base,
                "LMSTUDIO_CHAT_MODEL": chat.lmstudio_model,
            },
            provider=chat.provider,
        )
        return OpenAICompatibleChatClient(
            api_base=chat.lmstudio_api_base,
            api_key=chat.lmstudio_api_key,
            model=chat.lmstudio_model,
            provider="lmstudio_openai",
            timeout_seconds=max(1, chat.lmstudio_timeout_seconds),
        )

    if chat.provider == "codex_cli":
        _require_non_blank(
            {
                "CODEX_CMD": chat.codex_cmd,
            },
            provider=chat.provider,
        )
        return CodexChatClient(
            command=chat.codex_cmd,
            model=chat.codex_model or chat.model,
            workdir=chat.codex_workdir,
            output_schema=chat.codex_output_schema,
            timeout_seconds=chat.codex_timeout_seconds,
        )

    raise ChatConfigurationError(f"Unsupported chat provider: {chat.provider!r}")


def _require_non_blank(values: dict[str, str], *, provider: str) -> None:
    missing = [name for name, value in values.items() if not value.strip()]
    if missing:
        joined = ", ".join(missing)
        raise ChatConfigurationError(
            f"Missing chat configuration for {provider}: {joined}"
        )


def _extract_text_response(output: str) -> str:
    """Return plain text from possibly JSON-style provider output."""

    raw = output.strip()
    if not raw:
        return ""

    jsonl_text = _extract_jsonl_message(raw)
    if jsonl_text is not None:
        return jsonl_text

    json_candidates = [raw]
    if raw.startswith("```") and raw.endswith("```"):
        if "\n" in raw:
            inner = raw.split("\n", 1)[1].rsplit("\n", 1)[0]
            if inner.strip():
                json_candidates.append(inner.strip())

    for candidate in json_candidates:
        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict) and isinstance(parsed.get("answer"), str):
                    return parsed["answer"].strip()
                if isinstance(parsed, str):
                    return parsed.strip()
            except json.JSONDecodeError:
                pass

    return raw


def _extract_jsonl_message(output: str) -> str | None:
    last_message: str | None = None

    for line in output.splitlines():
        text = line.strip()
        if not text:
            continue
        if not (text.startswith("{") and text.endswith("}")):
            continue

        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            continue

        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "agent_message":
            continue
        message = item.get("text")
        if isinstance(message, str) and message.strip():
            last_message = message.strip()

    if last_message is None:
        return None

    if last_message.startswith("{") and last_message.endswith("}"):
        try:
            parsed = json.loads(last_message)
            if isinstance(parsed, dict) and isinstance(parsed.get("answer"), str):
                candidate = parsed["answer"].strip()
                if candidate:
                    return candidate
            if isinstance(parsed, str):
                candidate = parsed.strip()
                if candidate:
                    return candidate
        except json.JSONDecodeError:
            pass

    # Handle codex jsonl payloads that escape quotes one extra layer.
    try:
        unescaped = last_message.encode("utf-8").decode("unicode_escape")
    except (UnicodeDecodeError, UnicodeError):
        unescaped = last_message

    if unescaped != last_message and unescaped.startswith("{") and unescaped.endswith("}"):
        try:
            parsed = json.loads(unescaped)
            if isinstance(parsed, dict) and isinstance(parsed.get("answer"), str):
                candidate = parsed["answer"].strip()
                if candidate:
                    return candidate
            if isinstance(parsed, str):
                candidate = parsed.strip()
                if candidate:
                    return candidate
        except json.JSONDecodeError:
            pass

    return last_message


def _render_messages_as_prompt(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(
        f"{message['role']}: {message['content'].strip()}" for message in messages
    )


__all__ = [
    "ChatClient",
    "ChatConfigurationError",
    "ChatProviderError",
    "CodexChatClient",
    "OpenAICompatibleChatClient",
    "create_chat_client",
]

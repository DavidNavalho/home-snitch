from __future__ import annotations

import pytest

from homewiki.config import load_settings
from homewiki.llm import (
    ChatConfigurationError,
    CodexChatClient,
    OpenAICompatibleChatClient,
    _extract_text_response,
    create_chat_client,
)


def test_codex_cli_provider_returns_codex_client() -> None:
    client = create_chat_client(
        load_settings(
            environ={
                "CHAT_PROVIDER": "codex_cli",
                "CODEX_CMD": "/usr/bin/codex",
                "CODEX_MODEL": "gpt-4o-mini",
                "CODEX_TIMEOUT_SECONDS": "30",
                "CODEX_WORKDIR": ".demo/codex-runtime",
                "CODEX_OUTPUT_SCHEMA": "docs/schemas/home_wiki_answer.schema.json",
            }
        )
    )

    assert isinstance(client, CodexChatClient)
    assert client.provider == "codex_cli"
    assert client.command == "/usr/bin/codex"
    assert client.model == "gpt-4o-mini"
    assert client.timeout_seconds == 30
    assert client.workdir == ".demo/codex-runtime"
    assert client.output_schema.endswith("docs/schemas/home_wiki_answer.schema.json")


def test_lmstudio_provider_returns_openai_client_with_lmstudio_settings() -> None:
    client = create_chat_client(
        load_settings(
            environ={
                "CHAT_PROVIDER": "lmstudio_openai",
                "LMSTUDIO_API_BASE": "http://localhost:1234/v1",
                "LMSTUDIO_CHAT_MODEL": "qwen2.5-0.5b-instruct",
                "LMSTUDIO_API_KEY": "lm-studio",
                "LMSTUDIO_TIMEOUT_SECONDS": "45",
            }
        )
    )

    assert isinstance(client, OpenAICompatibleChatClient)
    assert client.provider == "lmstudio_openai"
    assert client.api_base == "http://localhost:1234/v1"
    assert client.api_key == "lm-studio"
    assert client.model == "qwen2.5-0.5b-instruct"
    assert client.timeout_seconds == 45


def test_openai_compatible_requires_model_setting() -> None:
    with pytest.raises(ChatConfigurationError):
        create_chat_client(
            load_settings(
                environ={
                    "CHAT_PROVIDER": "openai_compatible",
                    "CHAT_API_BASE": "http://localhost:1234/v1",
                }
            )
        )


def test_codex_cli_requires_command() -> None:
    with pytest.raises(ChatConfigurationError):
        create_chat_client(
            load_settings(
                environ={
                    "CHAT_PROVIDER": "codex_cli",
                    "CODEX_CMD": "",
                }
            )
        )


def test_extract_text_response_parses_codex_jsonl_agent_message() -> None:
    output = """
    {\"type\":\"thread.started\",\"thread_id\":\"x\"}
    {\"type\":\"turn.started\"}
    {\"type\":\"item.completed\",\"item\":{\"id\":\"item_0\",\"type\":\"agent_message\",\"text\":\"{\\\\\\\"answer\\\\\\\":\\\\\\\"All good\\\\\\\"}\"}}
    {\"type\":\"turn.completed\"}
    """
    assert _extract_text_response(output) == "All good"


def test_extract_text_response_parses_schema_json_payload() -> None:
    assert (
        _extract_text_response('{"answer": "OK"}') == "OK"
    )

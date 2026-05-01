"""Ask orchestration built on top of SearchResponse evidence."""

from __future__ import annotations

from typing import Protocol

from homewiki.config import Settings, load_settings
from homewiki.llm import ChatClient, ChatProviderError, create_chat_client
from homewiki.prompts import build_ask_messages
from homewiki.schemas import (
    AskRequest,
    AskResponse,
    ResolutionStatus,
    SearchRequest,
    SearchResponse,
    SearchResult,
)


class SearchCallable(Protocol):
    """Callable search dependency used by Ask service."""

    def __call__(self, request: SearchRequest) -> SearchResponse:
        """Return SearchResponse evidence for an Ask question."""


class SearchServiceUnavailable(RuntimeError):
    """Raised when Ask is called without a search implementation."""


def answer_question(
    request: AskRequest,
    *,
    search: SearchCallable,
    chat_client: ChatClient | None = None,
    settings: Settings | None = None,
) -> AskResponse:
    """Answer an AskRequest by searching first and optionally generating."""

    search_response = search(
        SearchRequest(
            query=request.question,
            asset_id=request.asset_id,
            limit=request.limit,
            allow_global_fallback=request.allow_global_fallback,
        )
    )

    if search_response.resolution.status == ResolutionStatus.AMBIGUOUS:
        return _ambiguous_response(search_response)

    evidence = _evidence_for_request(search_response.results, request)
    sources = _sources(evidence)
    if not evidence:
        return _missing_evidence_response(search_response)

    resolved_settings = settings or load_settings()
    resolved_chat_client = (
        chat_client
        if chat_client is not None
        else create_chat_client(resolved_settings)
    )
    if resolved_chat_client is None:
        return _evidence_only_response(search_response, evidence, sources)

    messages = build_ask_messages(request.question, evidence)
    try:
        answer = resolved_chat_client.complete(messages)
    except ChatProviderError:
        return _evidence_only_response(
            search_response,
            evidence,
            sources,
            prefix="Chat model failed. Retrieved evidence:",
        )

    if not answer.strip():
        return _evidence_only_response(
            search_response,
            evidence,
            sources,
            prefix="Chat model returned an empty answer. Retrieved evidence:",
        )

    return AskResponse(
        answer=answer,
        resolution=search_response.resolution,
        sources=sources,
        evidence=evidence,
        confidence=_confidence(evidence, generated=True),
        generated=True,
        missing_information=[],
    )


def default_search(request: SearchRequest) -> SearchResponse:
    """Search through the default G SearchService implementation."""

    try:
        from homewiki.search_service import create_search_service
    except ImportError as exc:
        raise SearchServiceUnavailable(
            "Ask API requires homewiki.search_service or an injected "
            "search callable"
        ) from exc
    return create_search_service().search(request)


def _ambiguous_response(search_response: SearchResponse) -> AskResponse:
    return AskResponse(
        answer="I found multiple matching devices. Select a device before asking again.",
        resolution=search_response.resolution,
        sources=[],
        evidence=[],
        confidence=0,
        generated=False,
        missing_information=["device selection"],
    )


def _missing_evidence_response(search_response: SearchResponse) -> AskResponse:
    return AskResponse(
        answer="The home wiki does not contain enough evidence to answer this question.",
        resolution=search_response.resolution,
        sources=[],
        evidence=[],
        confidence=0,
        generated=False,
        missing_information=["relevant indexed evidence"],
    )


def _evidence_only_response(
    search_response: SearchResponse,
    evidence: list[SearchResult],
    sources: list[str],
    *,
    prefix: str = "Chat is disabled. Retrieved evidence:",
) -> AskResponse:
    return AskResponse(
        answer=_evidence_only_answer(evidence, prefix=prefix),
        resolution=search_response.resolution,
        sources=sources,
        evidence=evidence,
        confidence=_confidence(evidence, generated=False),
        generated=False,
        missing_information=[],
    )


def _evidence_for_request(
    results: list[SearchResult],
    request: AskRequest,
) -> list[SearchResult]:
    if request.asset_id is None:
        return results
    return [result for result in results if result.asset_id == request.asset_id]


def _sources(evidence: list[SearchResult]) -> list[str]:
    sources: list[str] = []
    for result in evidence:
        source = result.markdown_path or result.source_path
        if source not in sources:
            sources.append(source)
    return sources


def _evidence_only_answer(
    evidence: list[SearchResult],
    *,
    prefix: str,
) -> str:
    snippets = []
    for result in evidence[:3]:
        source = result.markdown_path or result.source_path
        section = result.section_title or "Unsectioned"
        snippets.append(f"{result.text} Source: {source} ({section}).")
    return " ".join([prefix, *snippets])


def _confidence(evidence: list[SearchResult], *, generated: bool) -> int:
    if not evidence:
        return 0
    best_score = max((result.score or 0.0) for result in evidence)
    base = 7 if best_score >= 0.8 else 6
    if generated and best_score >= 0.8:
        return 8
    return base


__all__ = [
    "SearchCallable",
    "SearchServiceUnavailable",
    "answer_question",
    "default_search",
]

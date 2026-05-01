from __future__ import annotations

from typing import Any

from homewiki.ask_service import answer_question
from homewiki.config import load_settings
from homewiki.llm import ChatProviderError
from homewiki.schemas import (
    AskRequest,
    DeviceCandidate,
    DeviceResolution,
    ResolutionStatus,
    SearchFilters,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchScope,
    SourceType,
)


BOSCH_ASSET_ID = "dishwasher-bosch-sms6zcw00g"
SIEMENS_ASSET_ID = "dishwasher-siemens-sn23ec14cg"


def test_ambiguous_search_returns_candidates_without_chat() -> None:
    chat = RecordingChat(answer="Should not be used")
    request = AskRequest(question="dishwasher error code")

    response = answer_question(
        request,
        search=lambda search_request: _ambiguous_search(search_request.query),
        chat_client=chat,
        settings=_disabled_settings(),
    )

    assert response.generated is False
    assert response.evidence == []
    assert response.sources == []
    assert response.resolution.status == ResolutionStatus.AMBIGUOUS
    assert [candidate.asset_id for candidate in response.resolution.candidates] == [
        BOSCH_ASSET_ID,
        SIEMENS_ASSET_ID,
    ]
    assert chat.messages == []


def test_empty_search_returns_missing_information_without_chat() -> None:
    chat = RecordingChat(answer="Should not be used")

    response = answer_question(
        AskRequest(
            question="What is the warranty phone number?",
            asset_id=BOSCH_ASSET_ID,
        ),
        search=lambda search_request: _search_response(search_request.query, results=[]),
        chat_client=chat,
        settings=_disabled_settings(),
    )

    assert response.generated is False
    assert response.evidence == []
    assert response.confidence == 0
    assert response.missing_information == ["relevant indexed evidence"]
    assert "does not contain enough evidence" in response.answer
    assert chat.messages == []


def test_chat_disabled_returns_evidence_only_response_and_searches_first() -> None:
    events: list[str] = []

    def search(search_request: SearchRequest) -> SearchResponse:
        events.append("search")
        assert search_request.query == "What does E15 mean?"
        assert search_request.asset_id == BOSCH_ASSET_ID
        assert search_request.allow_global_fallback is False
        return _search_response(search_request.query, results=[_bosch_e15_result()])

    response = answer_question(
        AskRequest(question="What does E15 mean?", asset_id=BOSCH_ASSET_ID),
        search=search,
        settings=_disabled_settings(),
    )

    assert events == ["search"]
    assert response.generated is False
    assert response.confidence == 7
    assert response.sources == [
        "fixtures/markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
    ]
    assert response.evidence == [_bosch_e15_result()]
    assert "Chat is disabled" in response.answer
    assert "water protection system" in response.answer


def test_mock_chat_model_generates_grounded_answer_after_search() -> None:
    events: list[str] = []
    chat = RecordingChat(
        answer=(
            "E15 means the water protection system was activated, according to "
            "quick-manual.md > Troubleshooting > Error Codes > E15."
        ),
        events=events,
    )

    def search(search_request: SearchRequest) -> SearchResponse:
        events.append("search")
        return _search_response(search_request.query, results=[_bosch_e15_result()])

    response = answer_question(
        AskRequest(question="What does E15 mean?", asset_id=BOSCH_ASSET_ID),
        search=search,
        chat_client=chat,
        settings=_disabled_settings(),
    )

    assert events == ["search", "chat"]
    assert response.generated is True
    assert response.confidence == 8
    assert response.answer.startswith("E15 means")
    assert response.sources == [
        "fixtures/markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/quick-manual.md"
    ]
    assert chat.messages
    assert "Use only the provided home wiki evidence" in chat.messages[0]["content"]
    assert _bosch_e15_result().markdown_path in chat.messages[1]["content"]


def test_chat_provider_failure_falls_back_to_evidence_only() -> None:
    response = answer_question(
        AskRequest(question="What does E15 mean?", asset_id=BOSCH_ASSET_ID),
        search=lambda search_request: _search_response(
            search_request.query,
            results=[_bosch_e15_result()],
        ),
        chat_client=FailingChat(),
        settings=_disabled_settings(),
    )

    assert response.generated is False
    assert response.confidence == 7
    assert response.evidence == [_bosch_e15_result()]
    assert response.sources == [_bosch_e15_result().markdown_path]
    assert response.answer.startswith("Chat model failed. Retrieved evidence:")


def test_explicit_asset_filters_wrong_device_evidence_before_answering() -> None:
    wrong_result = _siemens_e24_result()
    right_result = _bosch_e15_result()

    response = answer_question(
        AskRequest(question="What does E15 mean?", asset_id=BOSCH_ASSET_ID),
        search=lambda search_request: _search_response(
            search_request.query,
            results=[wrong_result, right_result],
        ),
        settings=_disabled_settings(),
    )

    assert response.generated is False
    assert response.evidence == [right_result]
    assert response.sources == [right_result.markdown_path]
    assert wrong_result.text not in response.answer


class RecordingChat:
    provider = "test"

    def __init__(self, answer: str, events: list[str] | None = None) -> None:
        self.answer = answer
        self.events = events
        self.messages: list[dict[str, str]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        if self.events is not None:
            self.events.append("chat")
        self.messages = messages
        return self.answer


class FailingChat:
    provider = "test"

    def complete(self, messages: list[dict[str, str]]) -> str:
        raise ChatProviderError("test chat failure")


def _disabled_settings():
    return load_settings(environ={"CHAT_PROVIDER": "disabled"})


def _search_response(
    query: str,
    *,
    results: list[SearchResult],
    resolution: DeviceResolution | None = None,
) -> SearchResponse:
    return SearchResponse(
        query=query,
        resolution=resolution or _exact_resolution(),
        scope=SearchScope.DEVICE if results else SearchScope.NONE,
        results=results,
    )


def _ambiguous_search(query: str) -> SearchResponse:
    return _search_response(
        query,
        resolution=DeviceResolution(
            status=ResolutionStatus.AMBIGUOUS,
            confidence=0.65,
            matched_on=["device_type"],
            candidates=[
                DeviceCandidate(
                    asset_id=BOSCH_ASSET_ID,
                    confidence=0.65,
                    matched_on=["device_type"],
                    device_type="dishwasher",
                    brand="Bosch",
                    model="SMS6ZCW00G",
                    normalized_model="sms6zcw00g",
                    aliases=["kitchen dishwasher"],
                    room="kitchen",
                ),
                DeviceCandidate(
                    asset_id=SIEMENS_ASSET_ID,
                    confidence=0.65,
                    matched_on=["device_type"],
                    device_type="dishwasher",
                    brand="Siemens",
                    model="SN23EC14CG",
                    normalized_model="sn23ec14cg",
                    aliases=["utility dishwasher"],
                    room="utility",
                ),
            ],
            filters=SearchFilters(),
        ),
        results=[],
    )


def _exact_resolution() -> DeviceResolution:
    return DeviceResolution(
        status=ResolutionStatus.EXACT,
        asset_id=BOSCH_ASSET_ID,
        confidence=1.0,
        matched_on=["asset_id"],
        candidates=[],
        filters=SearchFilters(asset_id=BOSCH_ASSET_ID),
    )


def _bosch_e15_result(**overrides: Any) -> SearchResult:
    data = {
        "text": (
            "E15 means the water protection system has been activated or water "
            "has been detected in the base area."
        ),
        "score": 1.0,
        "asset_id": BOSCH_ASSET_ID,
        "source_type": SourceType.MANUAL,
        "brand": "Bosch",
        "model": "SMS6ZCW00G",
        "normalized_model": "sms6zcw00g",
        "device_type": "dishwasher",
        "room": "kitchen",
        "source_path": (
            "fixtures/source_docs/devices/dishwasher-bosch-sms6zcw00g/"
            "manuals/quick-manual.md"
        ),
        "markdown_path": (
            "fixtures/markdown_docs/devices/dishwasher-bosch-sms6zcw00g/"
            "manuals/quick-manual.md"
        ),
        "section_title": "Troubleshooting > Error Codes > E15",
        "chunk_index": 0,
        "content_hash": "bosch-e15",
        "modified_at": 0.0,
        "tags": ["appliance"],
    }
    data.update(overrides)
    return SearchResult.model_validate(data)


def _siemens_e24_result() -> SearchResult:
    return _bosch_e15_result(
        text="E24 means the drain system is blocked.",
        score=0.9,
        asset_id=SIEMENS_ASSET_ID,
        brand="Siemens",
        model="SN23EC14CG",
        normalized_model="sn23ec14cg",
        source_path=(
            "fixtures/source_docs/devices/dishwasher-siemens-sn23ec14cg/"
            "manuals/quick-manual.md"
        ),
        markdown_path=(
            "fixtures/markdown_docs/devices/dishwasher-siemens-sn23ec14cg/"
            "manuals/quick-manual.md"
        ),
        section_title="Troubleshooting > Error Codes > E24",
        content_hash="siemens-e24",
    )

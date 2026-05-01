"""Tiny deterministic orchestration layer for the Home Wiki API."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from homewiki.ask_service import answer_question
from homewiki.devices import DeviceStoreError, generate_asset_id, upsert_device
from homewiki.ingest import ingest_all
from homewiki.lancedb_store import open_store
from homewiki.llm import ChatClient, ChatConfigurationError
from homewiki.manuals import build_manual_search_query, download_manual, find_manual_candidates
from homewiki.schemas import (
    AgentAction,
    AgentExecuteRequest,
    AgentExecuteResponse,
    AgentExecutionStep,
    AgentPlanStep,
    AgentStepStatus,
    AgentToolCall,
    AskRequest,
    DeviceProfile,
    ErrorResponse,
    IncidentRequest,
    ManualDownloadRequest,
    ManualFindRequest,
    SearchRequest,
    normalize_model_identifier,
)
from homewiki.search_service import SearchService, SearchServiceError


_ACTION_INTENTS: dict[AgentAction, str] = {
    AgentAction.ASK: "answer_question",
    AgentAction.SEARCH: "search_docs",
    AgentAction.MANUAL_FIND: "manual_discovery",
    AgentAction.MANUAL_DOWNLOAD: "manual_download",
    AgentAction.INGEST: "index_refresh",
    AgentAction.ADD_DEVICE: "device_create",
    AgentAction.LIST_DEVICES: "device_list",
    AgentAction.INCIDENT: "incident_response",
}

_PREFIX_PATTERNS: dict[AgentAction, re.Pattern[str]] = {
    AgentAction.ASK: re.compile(r"^(?:/?ask|question)\b[:\s-]*", re.I),
    AgentAction.SEARCH: re.compile(
        r"^(?:/?search|find docs?|look up|lookup)\b[:\s-]*",
        re.I,
    ),
    AgentAction.MANUAL_FIND: re.compile(
        r"^(?:/?find manuals?|/?manuals? find|manual search)\b[:\s-]*",
        re.I,
    ),
    AgentAction.MANUAL_DOWNLOAD: re.compile(
        r"^(?:/?download|download manual)\b[:\s-]*",
        re.I,
    ),
    AgentAction.INGEST: re.compile(
        r"^(?:/?ingest|run ingest|index docs|reindex)\b[:\s-]*",
        re.I,
    ),
    AgentAction.ADD_DEVICE: re.compile(
        r"^(?:/?add device|new device|create device)\b[:\s-]*",
        re.I,
    ),
    AgentAction.LIST_DEVICES: re.compile(
        r"^(?:/?list devices?|show devices?|devices)\b[:\s-]*",
        re.I,
    ),
}

_KEY_VALUE_RE = re.compile(
    r"([a-zA-Z_][\w-]*)\s*=\s*(\"([^\"]*)\"|'([^']*)'|[^\s]+)"
)
_URL_RE = re.compile(r"https?://[^\s\"'<>]+|file://[^\s\"'<>]+", re.I)


def execute_agent(
    request: AgentExecuteRequest,
    *,
    service: SearchService,
    chat_client: ChatClient | None = None,
) -> AgentExecuteResponse:
    """Parse freeform input into one typed tool call, execute it, and report steps."""

    plan = build_agent_plan(request.input)
    steps: list[AgentExecutionStep] = []
    final_result: dict[str, Any] | None = None

    for plan_step in plan:
        try:
            result = _execute_tool_call(
                plan_step.tool_call,
                service=service,
                chat_client=chat_client,
            )
            final_result = result
            steps.append(
                AgentExecutionStep(
                    order=plan_step.order,
                    intent=plan_step.intent,
                    tool_call=plan_step.tool_call,
                    status=AgentStepStatus.SUCCESS,
                    result=result,
                )
            )
        except Exception as exc:  # noqa: BLE001 - agent response reports tool errors.
            steps.append(
                AgentExecutionStep(
                    order=plan_step.order,
                    intent=plan_step.intent,
                    tool_call=plan_step.tool_call,
                    status=AgentStepStatus.ERROR,
                    error=_error_from_exception(exc),
                )
            )
            break

    return AgentExecuteResponse(
        input=request.input,
        plan=plan,
        steps=steps,
        result=final_result,
    )


def build_agent_plan(input_text: str) -> list[AgentPlanStep]:
    """Return the strict one-step plan for the current tiny orchestrator."""

    tool_call = parse_tool_call(input_text)
    return [
        AgentPlanStep(
            order=1,
            intent=_ACTION_INTENTS[tool_call.action],
            tool_call=tool_call,
        )
    ]


def build_incident_plan(request: IncidentRequest) -> list[AgentPlanStep]:
    """Return a 3-step incident-response plan reusing existing tool calls.

    Step 1: SEARCH for the fault code on the asset.
    Step 2: ASK to interpret the fault code and recovery procedure.
    Step 3: SEARCH for replacement parts / suspected component.
    """

    fault = request.fault_code.strip()
    symptom = (request.symptom or "").strip()
    parts_query = symptom or f"replacement parts {fault}"

    step1 = AgentToolCall(
        action=AgentAction.SEARCH,
        inputs=SearchRequest(
            query=fault,
            asset_id=request.asset_id,
            limit=8,
            allow_global_fallback=False,
        ).to_json_dict(),
    )
    question = (
        f"What does fault code {fault} mean on this equipment, and what is "
        f"the recovery procedure? Cite the section."
    )
    if symptom:
        question += f" Observed symptom: {symptom}."
    step2 = AgentToolCall(
        action=AgentAction.ASK,
        inputs=AskRequest(
            question=question,
            asset_id=request.asset_id,
            limit=8,
            allow_global_fallback=False,
        ).to_json_dict(),
    )
    step3 = AgentToolCall(
        action=AgentAction.SEARCH,
        inputs=SearchRequest(
            query=parts_query,
            asset_id=request.asset_id,
            limit=6,
            allow_global_fallback=False,
        ).to_json_dict(),
    )
    return [
        AgentPlanStep(order=1, intent="incident_locate_fault", tool_call=step1),
        AgentPlanStep(order=2, intent="incident_recovery", tool_call=step2),
        AgentPlanStep(order=3, intent="incident_parts", tool_call=step3),
    ]


def execute_incident(
    request: IncidentRequest,
    *,
    service: SearchService,
    chat_client: ChatClient | None = None,
) -> AgentExecuteResponse:
    """Run the full 3-step incident plan and report each step's outcome."""

    plan = build_incident_plan(request)
    steps: list[AgentExecutionStep] = []
    final_result: dict[str, Any] | None = None

    for plan_step in plan:
        try:
            result = _execute_tool_call(
                plan_step.tool_call,
                service=service,
                chat_client=chat_client,
            )
            final_result = result
            steps.append(
                AgentExecutionStep(
                    order=plan_step.order,
                    intent=plan_step.intent,
                    tool_call=plan_step.tool_call,
                    status=AgentStepStatus.SUCCESS,
                    result=result,
                )
            )
        except Exception as exc:  # noqa: BLE001 - report tool errors per step.
            steps.append(
                AgentExecutionStep(
                    order=plan_step.order,
                    intent=plan_step.intent,
                    tool_call=plan_step.tool_call,
                    status=AgentStepStatus.ERROR,
                    error=_error_from_exception(exc),
                )
            )
            # Continue with remaining steps so the UI sees what's available.

    return AgentExecuteResponse(
        input=f"incident asset_id={request.asset_id} fault_code={request.fault_code}",
        plan=plan,
        steps=steps,
        result=final_result,
    )


def parse_tool_call(input_text: str) -> AgentToolCall:
    action = _detect_action(input_text)
    fields = _parse_key_values(input_text)
    command_text = _command_text(input_text, action)

    try:
        if action == AgentAction.ASK:
            return _tool_call(
                action,
                AskRequest(
                    question=_require_text(command_text, "ask"),
                    asset_id=_optional_string(fields.get("asset_id") or fields.get("asset")),
                    limit=_int_field(fields, "limit", 8, maximum=50),
                    allow_global_fallback=_bool_field(
                        fields,
                        "allow_global_fallback",
                        _bool_field(fields, "global", False),
                    ),
                ).to_json_dict(),
            )

        if action == AgentAction.SEARCH:
            return _tool_call(
                action,
                SearchRequest(
                    query=_require_text(command_text, "search"),
                    asset_id=_optional_string(fields.get("asset_id") or fields.get("asset")),
                    filters=None,
                    limit=_int_field(fields, "limit", 8, maximum=50),
                    allow_global_fallback=_bool_field(
                        fields,
                        "allow_global_fallback",
                        _bool_field(fields, "global", True),
                    ),
                ).to_json_dict(),
            )

        if action == AgentAction.MANUAL_FIND:
            return _tool_call(
                action,
                ManualFindRequest(
                    asset_id=_optional_string(fields.get("asset_id") or fields.get("asset")),
                    query=command_text or None,
                    limit=_int_field(fields, "limit", 5, maximum=20),
                ).to_json_dict(),
            )

        if action == AgentAction.MANUAL_DOWNLOAD:
            return _tool_call(
                action,
                ManualDownloadRequest(
                    asset_id=_required_field(
                        fields.get("asset_id") or fields.get("asset"),
                        "manual_download requires asset_id=<device>",
                    ),
                    url=_extract_url(input_text) or _required_field(
                        fields.get("url"),
                        "manual_download requires a URL",
                    ),
                ).to_json_dict(),
            )

        if action == AgentAction.INGEST:
            return _tool_call(action, {})

        if action == AgentAction.ADD_DEVICE:
            return _tool_call(
                action,
                _parse_device_profile(input_text, action).to_json_dict(),
            )

        if action == AgentAction.LIST_DEVICES:
            return _tool_call(action, {})
    except (ValidationError, ValueError) as exc:
        raise SearchServiceError(
            "agent_parse_error",
            f"Could not parse agent input for {action.value}.",
            status_code=422,
            details=_parse_error_details(exc),
        ) from exc

    raise SearchServiceError(
        "agent_unknown_action",
        f"Unsupported agent action {action.value!r}.",
        status_code=422,
    )


def _execute_tool_call(
    tool_call: AgentToolCall,
    *,
    service: SearchService,
    chat_client: ChatClient | None,
) -> dict[str, Any]:
    inputs = tool_call.inputs

    if tool_call.action == AgentAction.ASK:
        response = answer_question(
            AskRequest.model_validate(inputs),
            search=service.search,
            chat_client=chat_client,
            settings=service.settings,
        )
        return response.to_json_dict()

    if tool_call.action == AgentAction.SEARCH:
        return service.search(SearchRequest.model_validate(inputs)).to_json_dict()

    if tool_call.action == AgentAction.MANUAL_FIND:
        return _find_manuals(
            ManualFindRequest.model_validate(inputs),
            service=service,
        ).to_json_dict()

    if tool_call.action == AgentAction.MANUAL_DOWNLOAD:
        request = ManualDownloadRequest.model_validate(inputs)
        return download_manual(
            asset_id=request.asset_id,
            url=request.url,
            source_root=service.settings.paths.source_docs,
        ).to_json_dict()

    if tool_call.action == AgentAction.INGEST:
        store = open_store(service.settings)
        return ingest_all(
            source_root=service.settings.paths.source_docs,
            markdown_root=service.settings.paths.markdown_docs,
            store=store,
        ).to_json_dict()

    if tool_call.action == AgentAction.ADD_DEVICE:
        profile = DeviceProfile.model_validate(inputs)
        saved = upsert_device(profile, settings=service.settings)
        return {"device": saved.to_json_dict()}

    if tool_call.action == AgentAction.LIST_DEVICES:
        return {"devices": [device.to_json_dict() for device in service.list_devices()]}

    raise SearchServiceError(
        "agent_unknown_action",
        f"Unsupported agent action {tool_call.action.value!r}.",
        status_code=422,
    )


def _find_manuals(
    request: ManualFindRequest,
    *,
    service: SearchService,
):
    profile = _resolve_device_for_asset(service, request.asset_id)
    if profile is None and not request.query:
        raise SearchServiceError(
            "unknown_asset_id",
            f"device asset_id {request.asset_id!r} is not registered.",
            status_code=404,
            details={"asset_id": request.asset_id},
        )

    if profile is not None:
        brand = profile.brand
        model = profile.model
        device_type = profile.device_type
        query = request.query or build_manual_search_query(
            brand=brand,
            model=model,
            device_type=device_type,
        )
    else:
        assert request.query is not None
        query = request.query
        brand, model, device_type = _parse_manual_query(request.query)

    result = find_manual_candidates(
        brand=brand,
        model=model,
        device_type=device_type or None,
        limit=request.limit,
    )
    return result.model_copy(update={"query": query})


def _detect_action(input_text: str) -> AgentAction:
    lower = _compact(input_text).lower()
    for action in (
        AgentAction.LIST_DEVICES,
        AgentAction.INGEST,
        AgentAction.MANUAL_DOWNLOAD,
        AgentAction.MANUAL_FIND,
        AgentAction.ADD_DEVICE,
        AgentAction.SEARCH,
        AgentAction.ASK,
    ):
        if _PREFIX_PATTERNS[action].search(lower):
            return action

    if not lower:
        return AgentAction.ASK
    if "device" in lower and any(term in lower for term in ("list", "show")):
        return AgentAction.LIST_DEVICES
    if "manual" in lower and ("download" in lower or _URL_RE.search(lower)):
        return AgentAction.MANUAL_DOWNLOAD
    if "manual" in lower:
        return AgentAction.MANUAL_FIND
    if "device" in lower and any(term in lower for term in ("add", "new", "create")):
        return AgentAction.ADD_DEVICE
    if any(lower.startswith(term) for term in ("search", "find", "lookup", "look up")):
        return AgentAction.SEARCH
    return AgentAction.ASK


def _tool_call(action: AgentAction, inputs: dict[str, Any]) -> AgentToolCall:
    return AgentToolCall(action=action, inputs=inputs)


def _parse_key_values(input_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _KEY_VALUE_RE.finditer(input_text):
        key = match.group(1).lower().replace("-", "_")
        fields[key] = match.group(3) or match.group(4) or match.group(2) or ""
    return fields


def _command_text(input_text: str, action: AgentAction) -> str:
    without_keys = _KEY_VALUE_RE.sub("", input_text)
    without_prefix = _PREFIX_PATTERNS[action].sub("", without_keys, count=1)
    return _compact(without_prefix)


def _extract_url(input_text: str) -> str | None:
    match = _URL_RE.search(input_text)
    return match.group(0) if match else None


def _parse_device_profile(input_text: str, action: AgentAction) -> DeviceProfile:
    after_prefix = _PREFIX_PATTERNS[action].sub("", input_text.strip(), count=1)
    parsed_json = _parse_json_object(after_prefix)
    fields = parsed_json or _parse_key_values(after_prefix)
    normalized = {
        str(key).lower().replace("-", "_"): value for key, value in fields.items()
    }
    device_type = _required_field(
        normalized.get("device_type") or normalized.get("type"),
        "add_device requires type=<device_type>",
    )
    brand = _required_field(normalized.get("brand"), "add_device requires brand=<brand>")
    model = _required_field(normalized.get("model"), "add_device requires model=<model>")
    asset_id = _optional_string(normalized.get("asset_id")) or generate_asset_id(
        device_type,
        brand,
        model,
    )
    aliases = _list_field(normalized.get("aliases") or normalized.get("alias"))
    tags = _list_field(normalized.get("tags") or normalized.get("tag"))

    return DeviceProfile(
        asset_id=asset_id,
        device_type=device_type,
        brand=brand,
        model=model,
        normalized_model=_optional_string(normalized.get("normalized_model"))
        or normalize_model_identifier(model),
        aliases=aliases,
        room=_optional_string(normalized.get("room")),
        serial_number=_optional_string(
            normalized.get("serial_number") or normalized.get("serial")
        ),
        support_url=_optional_string(normalized.get("support_url")),
        notes=_optional_string(normalized.get("notes")),
        tags=tags,
    )


def _parse_json_object(input_text: str) -> dict[str, Any] | None:
    text = input_text.strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _int_field(
    fields: dict[str, str],
    key: str,
    default: int,
    *,
    maximum: int,
) -> int:
    raw = fields.get(key)
    if raw is None or raw == "":
        return default
    value = int(raw)
    if value < 1 or value > maximum:
        raise ValueError(f"{key} must be between 1 and {maximum}")
    return value


def _bool_field(fields: dict[str, str], key: str, default: bool) -> bool:
    raw = fields.get(key)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _list_field(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _required_field(value: Any, message: str) -> str:
    normalized = _optional_string(value)
    if normalized is None:
        raise ValueError(message)
    return normalized


def _require_text(value: str, action: str) -> str:
    if not value:
        raise ValueError(f"{action} requires text")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _error_from_exception(exc: Exception) -> ErrorResponse:
    if isinstance(exc, SearchServiceError):
        return exc.error
    if isinstance(exc, ChatConfigurationError):
        return ErrorResponse(code="chat_configuration_error", message=str(exc))
    if isinstance(exc, DeviceStoreError):
        return ErrorResponse(code="device_store_error", message=str(exc))
    if isinstance(exc, ValidationError):
        return ErrorResponse(
            code="validation_error",
            message="Tool input validation failed.",
            details={"errors": exc.errors()},
        )
    return ErrorResponse(code="agent_tool_error", message=str(exc))


def _parse_error_details(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ValidationError):
        return {"errors": exc.errors()}
    return {"cause": str(exc)}


def _resolve_device_for_asset(
    service: SearchService,
    asset_id: str | None,
) -> DeviceProfile | None:
    if not asset_id:
        return None

    for device in service.list_devices():
        if device.asset_id == asset_id:
            return device
    return None


def _parse_manual_query(query: str) -> tuple[str, str, str | None]:
    parts = [part.strip() for part in query.split() if part.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1], None
    if len(parts) == 1:
        return parts[0], "", None
    return "", "", None


__all__ = [
    "build_agent_plan",
    "build_incident_plan",
    "execute_agent",
    "execute_incident",
    "parse_tool_call",
]

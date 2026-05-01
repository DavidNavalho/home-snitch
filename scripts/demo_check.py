#!/usr/bin/env python3
"""Run deterministic Home Wiki demo scenario checks.

Fixture mode validates checked-in contracts and UI payloads without touching the
index. Retrieval mode builds the fixture index with fake embeddings, then checks
Search and Ask wiring in chat-disabled evidence-only mode.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from homewiki.ask_service import answer_question  # noqa: E402
from homewiki.config import find_project_root  # noqa: E402
from homewiki.ingest import ingest_all  # noqa: E402
from homewiki.lancedb_store import open_store  # noqa: E402
from homewiki.manuals import parse_manual_search_html  # noqa: E402
from homewiki.resolver import load_device_profiles, resolve_device  # noqa: E402
from homewiki.schemas import (  # noqa: E402
    AskRequest,
    AskResponse,
    DeviceProfile,
    ManualSearchResult,
    SearchRequest,
    SearchResponse,
)
from homewiki.search_service import SearchService, SearchServiceError  # noqa: E402
from scripts.demo_seed import demo_settings, resolve_demo_workspace  # noqa: E402


REQUIRED_SCENARIOS = {
    "DEMO-01",
    "DEMO-02",
    "DEMO-03",
    "DEMO-04",
    "DEMO-05",
    "DEMO-06",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("fixture", "retrieval"),
        default="fixture",
        help="Demo layer to check. Retrieval mode requires a seeded and indexed workspace.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Demo workspace. Defaults to <project>/.demo.",
    )
    parser.add_argument("--json", action="store_true", help="Print a JSON report.")
    args = parser.parse_args(argv)

    project_root = find_project_root(ROOT)
    workspace = resolve_demo_workspace(args.workspace, project_root)

    if args.mode == "fixture":
        report = check_fixture_mode(project_root, workspace)
    else:
        report = check_retrieval_mode(project_root, workspace)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_text_report(report)
    return 0 if report["status"] == "ok" else 1


def check_fixture_mode(project_root: Path, workspace: Path) -> dict[str, Any]:
    fixtures_root = project_root / "fixtures"
    scenarios_path = fixtures_root / "demo" / "scenarios.json"
    scenario_doc = load_json(scenarios_path)
    scenarios = scenario_doc.get("scenarios", [])
    devices = load_fixture_devices(fixtures_root)

    checks: list[dict[str, Any]] = []
    checks.append(check_required_scenarios(scenarios))
    checks.append(check_devices_fixture(fixtures_root))

    for scenario in scenarios:
        checks.extend(check_scenario(project_root, scenario, devices))

    if (workspace / "demo_manifest.json").exists():
        checks.append(check_seeded_workspace(project_root, workspace))

    return build_report("fixture", checks, workspace=workspace)


def check_retrieval_mode(project_root: Path, workspace: Path) -> dict[str, Any]:
    settings = demo_settings(project_root, workspace)
    checks: list[dict[str, Any]] = []

    seeded = check_seeded_workspace(project_root, workspace)
    checks.append(seeded)
    if seeded["status"] != "ok":
        return build_report("retrieval", checks, workspace=workspace)

    try:
        store = open_store(settings)
        ingest_report = ingest_all(
            source_root=settings.paths.source_docs,
            markdown_root=settings.paths.markdown_docs,
            store=store,
            force_convert=True,
            force_index=True,
        )
    except Exception as exc:  # noqa: BLE001 - report as demo check failure.
        checks.append(fail("retrieval-ingest", str(exc)))
        return build_report("retrieval", checks, workspace=workspace)

    if ingest_report.failed:
        checks.append(
            fail(
                "retrieval-ingest",
                "ingest failed: "
                + "; ".join(error.message for error in ingest_report.errors),
            )
        )
        return build_report("retrieval", checks, workspace=workspace)
    checks.append(
        ok(
            "retrieval-ingest",
            f"indexed={ingest_report.indexed} skipped={ingest_report.skipped}",
        )
    )

    status = store.status()
    if status.get("status") == "ok" and status.get("row_count", 0) > 0:
        checks.append(ok("retrieval-index-status", f"row_count={status['row_count']}"))
    else:
        checks.append(
            fail(
                "retrieval-index-status",
                f"retrieval mode requires an indexed LanceDB table: {status}",
            )
        )
        return build_report("retrieval", checks, workspace=workspace)

    service = SearchService(settings=settings)
    checks.append(
        check_retrieval_search(
            "retrieval-exact-device",
            service,
            SearchRequest(
                query="What does E15 mean on SMS6ZCW00G?",
                limit=8,
                allow_global_fallback=False,
            ),
            expected_resolution={
                "status": "exact",
                "asset_id": "dishwasher-bosch-sms6zcw00g",
            },
            expected_scope="device",
            expected_terms=["E15", "water protection"],
            forbidden_terms=["Siemens", "SN23EC14CG"],
        )
    )
    checks.append(
        check_retrieval_search(
            "retrieval-alias-device",
            service,
            SearchRequest(
                query="What does E15 mean on the kitchen dishwasher?",
                limit=8,
                allow_global_fallback=False,
            ),
            expected_resolution={
                "status": "exact",
                "asset_id": "dishwasher-bosch-sms6zcw00g",
            },
            expected_scope="device",
            expected_terms=["E15", "water protection"],
            forbidden_terms=["Siemens", "SN23EC14CG"],
        )
    )
    checks.append(
        check_retrieval_search(
            "retrieval-ambiguous-device",
            service,
            SearchRequest(query="dishwasher error code", limit=8),
            expected_resolution={
                "status": "ambiguous",
                "candidate_asset_ids": [
                    "dishwasher-bosch-sms6zcw00g",
                    "dishwasher-siemens-sn23ec14cg",
                ],
            },
            expected_scope="none",
            expected_terms=[],
            forbidden_terms=["water protection system has been activated"],
        )
    )
    checks.append(
        check_retrieval_search(
            "retrieval-router-note",
            service,
            SearchRequest(
                query="Where is the router admin URL documented?",
                limit=8,
                allow_global_fallback=True,
            ),
            expected_resolution={
                "status": "exact",
                "asset_id": "router-asus-rt-ax88u",
            },
            expected_scope="device",
            expected_terms=["http://router.asus.com"],
            forbidden_terms=["default password"],
        )
    )
    checks.append(
        check_retrieval_ask(
            "retrieval-ask-e15",
            service,
            AskRequest(
                question="What does E15 mean on SMS6ZCW00G?",
                limit=8,
                allow_global_fallback=False,
            ),
            expected_resolution={
                "status": "exact",
                "asset_id": "dishwasher-bosch-sms6zcw00g",
            },
            expected_terms=["Chat is disabled", "E15", "water protection"],
            forbidden_terms=["Siemens", "SN23EC14CG"],
            evidence_required=True,
        )
    )
    checks.append(
        check_retrieval_ask(
            "retrieval-ask-ambiguous",
            service,
            AskRequest(question="dishwasher error code", limit=8),
            expected_resolution={
                "status": "ambiguous",
                "candidate_asset_ids": [
                    "dishwasher-bosch-sms6zcw00g",
                    "dishwasher-siemens-sn23ec14cg",
                ],
            },
            expected_terms=["device selection"],
            forbidden_terms=["water protection system has been activated"],
            missing_information_required=True,
        )
    )
    checks.append(
        check_retrieval_ask(
            "retrieval-ask-router-note",
            service,
            AskRequest(
                question="Where is the router admin URL documented?",
                limit=8,
                allow_global_fallback=True,
            ),
            expected_resolution={
                "status": "exact",
                "asset_id": "router-asus-rt-ax88u",
            },
            expected_terms=["Chat is disabled", "http://router.asus.com"],
            forbidden_terms=["default password"],
            evidence_required=True,
        )
    )

    return build_report("retrieval", checks, workspace=workspace)


def check_retrieval_search(
    check_id: str,
    service: SearchService,
    request: SearchRequest,
    *,
    expected_resolution: dict[str, Any],
    expected_scope: str,
    expected_terms: list[str],
    forbidden_terms: list[str],
) -> dict[str, Any]:
    try:
        response = service.search(request)
    except SearchServiceError as exc:
        return fail(check_id, exc.error.message)

    failures = response_expectation_failures(
        {
            "expected_resolution": expected_resolution,
            "expected_scope": expected_scope,
            "expected_evidence_terms": expected_terms,
            "forbidden_terms": forbidden_terms,
            "expected_sources": [],
            "expected_ui_state": {"generated": False},
        },
        response,
    )
    if expected_scope != "none" and not response.results:
        failures.append("response returned no retrieval results")

    if failures:
        return fail(check_id, "; ".join(failures))
    return ok(check_id, "real retrieval search expectation passed")


def check_retrieval_ask(
    check_id: str,
    service: SearchService,
    request: AskRequest,
    *,
    expected_resolution: dict[str, Any],
    expected_terms: list[str],
    forbidden_terms: list[str],
    evidence_required: bool = False,
    missing_information_required: bool = False,
) -> dict[str, Any]:
    try:
        response = answer_question(
            request,
            search=service.search,
            settings=service.settings,
        )
    except SearchServiceError as exc:
        return fail(check_id, exc.error.message)
    except Exception as exc:  # noqa: BLE001 - report as demo check failure.
        return fail(check_id, str(exc))

    failures = response_expectation_failures(
        {
            "expected_resolution": expected_resolution,
            "expected_evidence_terms": expected_terms,
            "forbidden_terms": forbidden_terms,
            "expected_sources": [],
            "expected_ui_state": {
                "generated": False,
                "requires_missing_information": missing_information_required,
            },
        },
        response,
    )
    if evidence_required and not response.evidence:
        failures.append("response returned no Ask evidence")

    if failures:
        return fail(check_id, "; ".join(failures))
    return ok(check_id, "real retrieval Ask expectation passed")


def check_scenario(
    project_root: Path,
    scenario: dict[str, Any],
    devices: list[DeviceProfile],
) -> list[dict[str, Any]]:
    checks = [check_scenario_shape(scenario), check_scenario_fixtures(project_root, scenario)]
    scenario_id = scenario.get("id", "unknown")
    kind = scenario.get("kind")

    if kind in {"ask", "search"}:
        checks.append(check_request_shape(scenario_id, kind, scenario.get("request", {})))
        checks.append(check_resolver_expectation(scenario_id, scenario, devices))

    if "response_fixture" in scenario or "fixture_response" in scenario:
        checks.append(check_response_expectation(project_root, scenario))
    elif kind == "manual_find":
        checks.append(check_manual_expectation(project_root, scenario))

    return checks


def check_scenario_shape(scenario: dict[str, Any]) -> dict[str, Any]:
    scenario_id = scenario.get("id", "unknown")
    required = {
        "id",
        "title",
        "layer",
        "kind",
        "request",
        "expected_resolution",
        "expected_evidence_terms",
        "forbidden_terms",
        "expected_ui_state",
    }
    missing = sorted(required - set(scenario))
    if missing:
        return fail(scenario_id, f"scenario missing keys: {', '.join(missing)}")
    return ok(scenario_id, "scenario shape is complete")


def check_scenario_fixtures(project_root: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    scenario_id = scenario.get("id", "unknown")
    missing = [
        path
        for path in scenario.get("fixtures", [])
        if not (project_root / path).exists()
    ]
    if scenario.get("response_fixture") and not (
        project_root / scenario["response_fixture"]
    ).exists():
        missing.append(scenario["response_fixture"])
    if missing:
        return fail(scenario_id, f"missing fixture files: {', '.join(missing)}")
    return ok(scenario_id, "fixture files exist")


def check_request_shape(
    scenario_id: str,
    kind: str,
    request: dict[str, Any],
) -> dict[str, Any]:
    try:
        if kind == "ask":
            AskRequest.model_validate(request)
        else:
            SearchRequest.model_validate(request)
    except Exception as exc:  # noqa: BLE001 - pydantic detail is enough.
        return fail(scenario_id, f"request does not match shared schema: {exc}")
    return ok(scenario_id, "request matches shared schema")


def check_resolver_expectation(
    scenario_id: str,
    scenario: dict[str, Any],
    devices: list[DeviceProfile],
) -> dict[str, Any]:
    request = scenario.get("request", {})
    query = request.get("question") or request.get("query") or ""
    resolution = resolve_device(
        query,
        asset_id=request.get("asset_id"),
        devices=devices,
    )
    expected = scenario.get("expected_resolution", {})

    failures: list[str] = []
    if expected.get("status") and resolution.status.value != expected["status"]:
        failures.append(
            f"status {resolution.status.value!r} != {expected['status']!r}"
        )
    if expected.get("asset_id") and resolution.asset_id != expected["asset_id"]:
        failures.append(
            f"asset_id {resolution.asset_id!r} != {expected['asset_id']!r}"
        )
    expected_candidates = set(expected.get("candidate_asset_ids", []))
    if expected_candidates:
        actual_candidates = {candidate.asset_id for candidate in resolution.candidates}
        if not expected_candidates.issubset(actual_candidates):
            failures.append(
                "candidates missing "
                f"{sorted(expected_candidates - actual_candidates)}"
            )

    if failures:
        return fail(scenario_id, "; ".join(failures))
    return ok(scenario_id, "resolver expectation passed")


def check_response_expectation(project_root: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    scenario_id = scenario.get("id", "unknown")
    response_type = scenario.get("response_type")
    payload = scenario.get("fixture_response")
    if payload is None:
        payload = load_json(project_root / scenario["response_fixture"])

    try:
        response = validate_response_payload(response_type, payload)
    except Exception as exc:  # noqa: BLE001 - pydantic detail is enough.
        return fail(scenario_id, f"response does not match shared schema: {exc}")

    failures = response_expectation_failures(scenario, response)
    if failures:
        return fail(scenario_id, "; ".join(failures))
    return ok(scenario_id, "response expectation passed")


def check_manual_expectation(project_root: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    scenario_id = scenario.get("id", "unknown")
    request = scenario.get("request", {})
    html_path = project_root / request["fixture_html"]
    html = html_path.read_text(encoding="utf-8")
    result = parse_manual_search_html(
        html,
        query=request["query"],
        brand=request.get("brand"),
        model=request.get("model"),
        device_type=request.get("device_type"),
    )
    result = ManualSearchResult.model_validate(result.to_json_dict())
    failures = response_expectation_failures(scenario, result)
    if failures:
        return fail(scenario_id, "; ".join(failures))
    return ok(scenario_id, "manual fixture expectation passed")


def validate_response_payload(response_type: str, payload: dict[str, Any]) -> Any:
    if response_type == "ask":
        return AskResponse.model_validate(payload)
    if response_type == "search":
        return SearchResponse.model_validate(payload)
    if response_type == "manual_find":
        return ManualSearchResult.model_validate(payload)
    raise ValueError(f"unsupported response_type {response_type!r}")


def response_expectation_failures(scenario: dict[str, Any], response: Any) -> list[str]:
    expected = scenario.get("expected_resolution", {})
    failures: list[str] = []

    resolution = getattr(response, "resolution", None)
    if resolution is not None:
        if expected.get("status") and resolution.status.value != expected["status"]:
            failures.append(
                f"response status {resolution.status.value!r} != {expected['status']!r}"
            )
        if expected.get("asset_id") and resolution.asset_id != expected["asset_id"]:
            failures.append(
                f"response asset_id {resolution.asset_id!r} != {expected['asset_id']!r}"
            )
        expected_candidates = set(expected.get("candidate_asset_ids", []))
        if expected_candidates:
            actual_candidates = {candidate.asset_id for candidate in resolution.candidates}
            if not expected_candidates.issubset(actual_candidates):
                failures.append(
                    "response candidates missing "
                    f"{sorted(expected_candidates - actual_candidates)}"
                )

    expected_scope = scenario.get("expected_scope")
    if expected_scope and hasattr(response, "scope") and response.scope.value != expected_scope:
        failures.append(f"scope {response.scope.value!r} != {expected_scope!r}")

    text = searchable_response_text(response)
    for term in scenario.get("expected_evidence_terms", []):
        if term.lower() not in text.lower():
            failures.append(f"missing evidence term {term!r}")
    for term in scenario.get("forbidden_terms", []):
        if term.lower() in text.lower():
            failures.append(f"forbidden term present {term!r}")

    for source in scenario.get("expected_sources", []):
        if source not in text:
            failures.append(f"missing source {source!r}")

    ui_state = scenario.get("expected_ui_state", {})
    if ui_state.get("generated") is False and getattr(response, "generated", False):
        failures.append("response unexpectedly generated an answer")
    if ui_state.get("requires_missing_information") and not getattr(
        response, "missing_information", []
    ):
        failures.append("response is missing missing_information entries")
    if ui_state.get("shows_candidates"):
        candidates = getattr(resolution, "candidates", []) if resolution else []
        candidate_ids = {candidate.asset_id for candidate in candidates}
        expected_ids = set(ui_state["shows_candidates"])
        if not expected_ids.issubset(candidate_ids):
            failures.append(f"UI candidates missing {sorted(expected_ids - candidate_ids)}")

    return failures


def searchable_response_text(response: Any) -> str:
    parts: list[str] = []
    if isinstance(response, AskResponse):
        parts.extend([response.answer, *response.sources, *response.missing_information])
        parts.extend(search_result_text(item) for item in response.evidence)
    elif isinstance(response, SearchResponse):
        parts.append(response.query)
        parts.extend(search_result_text(item) for item in response.results)
    elif isinstance(response, ManualSearchResult):
        parts.append(response.query)
        for candidate in response.candidates:
            parts.extend([candidate.title, candidate.url, candidate.source_host or ""])
    return "\n".join(parts)


def search_result_text(result: Any) -> str:
    return "\n".join(
        [
            result.text,
            result.source_path,
            result.markdown_path,
            result.section_title,
            result.asset_id or "",
            result.source_type.value,
        ]
    )


def check_required_scenarios(scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    ids = {scenario.get("id") for scenario in scenarios}
    missing = sorted(REQUIRED_SCENARIOS - ids)
    if missing:
        return fail("required-scenarios", f"missing scenarios: {', '.join(missing)}")
    return ok("required-scenarios", "all required demo scenarios exist")


def check_devices_fixture(fixtures_root: Path) -> dict[str, Any]:
    payload = load_json(fixtures_root / "api" / "devices-list.json")
    try:
        devices = [DeviceProfile.model_validate(item) for item in payload["devices"]]
    except Exception as exc:  # noqa: BLE001 - pydantic detail is enough.
        return fail("devices-fixture", f"devices fixture is invalid: {exc}")
    if len(devices) < 3:
        return fail("devices-fixture", "expected at least three fixture devices")
    return ok("devices-fixture", "devices fixture matches shared schema")


def check_seeded_workspace(project_root: Path, workspace: Path) -> dict[str, Any]:
    settings = demo_settings(project_root, workspace)
    expected_paths = [
        settings.paths.source_docs / "devices",
        settings.paths.markdown_docs / "devices",
        settings.paths.device_registry,
        workspace / "api",
        workspace / "scenarios.json",
    ]
    missing = [str(path) for path in expected_paths if not path.exists()]
    if missing:
        return fail("seeded-workspace", f"seeded workspace missing: {missing}")
    return ok("seeded-workspace", "seeded workspace paths exist")


def load_fixture_devices(fixtures_root: Path) -> list[DeviceProfile]:
    return load_device_profiles(fixtures_root / "source_docs")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ok(check_id: str, message: str) -> dict[str, Any]:
    return {"id": check_id, "status": "ok", "message": message}


def fail(check_id: str, message: str) -> dict[str, Any]:
    return {"id": check_id, "status": "fail", "message": message}


def build_report(mode: str, checks: list[dict[str, Any]], *, workspace: Path) -> dict[str, Any]:
    failed = [check for check in checks if check["status"] != "ok"]
    return {
        "status": "ok" if not failed else "fail",
        "mode": mode,
        "workspace": str(workspace),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "checks": checks,
    }


def print_text_report(report: dict[str, Any]) -> None:
    print(
        f"Demo check {report['status']} "
        f"({report['mode']}: {report['passed']} passed, {report['failed']} failed)"
    )
    for check in report["checks"]:
        marker = "PASS" if check["status"] == "ok" else "FAIL"
        print(f"{marker} {check['id']}: {check['message']}")


if __name__ == "__main__":
    raise SystemExit(main())

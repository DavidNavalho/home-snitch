from datetime import date, datetime, timezone
from unittest import TestCase

from pydantic import ValidationError

from homewiki.schemas import (
    AgentAction,
    AgentExecuteRequest,
    AgentExecuteResponse,
    AgentPlanStep,
    AgentStepStatus,
    AgentToolCall,
    DeviceResolution,
    DeviceProfile,
    ErrorResponse,
    IndexChunk,
    ResolutionStatus,
    SearchFilters,
    SourceType,
    normalize_model_identifier,
)


class SchemaTests(TestCase):
    def test_import_schemas_without_lancedb(self) -> None:
        import homewiki.schemas as schemas

        self.assertTrue(hasattr(schemas, "DeviceProfile"))

    def test_complete_device_profile_validates_and_serializes(self) -> None:
        profile = DeviceProfile(
            asset_id="dishwasher-bosch-sms6zcw00g",
            device_type="dishwasher",
            brand="Bosch",
            model="SMS6ZCW00G",
            normalized_model="sms6zcw00g",
            aliases=["kitchen dishwasher", "dishwasher"],
            room="kitchen",
            serial_number="ABC123",
            purchase_date=date(2024, 4, 30),
            warranty_until=date(2028, 4, 30),
            support_url="https://example.com/support",
            notes="Under counter.",
            tags=["appliance"],
            created_at=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 1, 13, 0, tzinfo=timezone.utc),
        )

        serialized = profile.to_json_dict()

        self.assertEqual(serialized["asset_id"], "dishwasher-bosch-sms6zcw00g")
        self.assertEqual(serialized["purchase_date"], "2024-04-30")
        self.assertEqual(serialized["created_at"], "2026-05-01T12:00:00Z")

    def test_minimal_device_profile_defaults_optional_fields(self) -> None:
        profile = DeviceProfile(
            asset_id="router-asus-rt-ax88u",
            device_type="router",
            brand="ASUS",
            model="RT-AX88U",
            normalized_model="rtax88u",
        )

        self.assertEqual(profile.aliases, [])
        self.assertEqual(profile.tags, [])
        self.assertIsNone(profile.room)
        self.assertIsNone(profile.serial_number)

    def test_normalized_model_must_match_model_rule(self) -> None:
        with self.assertRaises(ValidationError):
            DeviceProfile(
                asset_id="router-asus-rt-ax88u",
                device_type="router",
                brand="ASUS",
                model="RT-AX88U",
                normalized_model="rt-ax88u",
            )

    def test_invalid_source_type_fails(self) -> None:
        with self.assertRaises(ValidationError):
            IndexChunk(
                text="E15 means water protection activated.",
                asset_id="dishwasher-bosch-sms6zcw00g",
                source_type="unsupported",
                brand="Bosch",
                model="SMS6ZCW00G",
                normalized_model="sms6zcw00g",
                device_type="dishwasher",
                room="kitchen",
                source_path="source_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/manual.pdf",
                markdown_path="markdown_docs/devices/dishwasher-bosch-sms6zcw00g/manuals/manual.pdf.md",
                section_title="Troubleshooting > Error Codes",
                chunk_index=0,
                content_hash="abc123",
                modified_at=0.0,
                tags=["appliance"],
            )

    def test_invalid_resolution_status_fails(self) -> None:
        with self.assertRaises(ValidationError):
            DeviceResolution(
                status="maybe",
                asset_id=None,
                confidence=0.0,
                matched_on=[],
                candidates=[],
                filters=SearchFilters(),
            )

    def test_exact_resolution_requires_asset_id(self) -> None:
        with self.assertRaises(ValidationError):
            DeviceResolution(
                status=ResolutionStatus.EXACT,
                confidence=0.95,
                matched_on=["model"],
                filters=SearchFilters(asset_id="dishwasher-bosch-sms6zcw00g"),
            )

    def test_resolution_serializes_enum_values_for_api_payloads(self) -> None:
        resolution = DeviceResolution(
            status=ResolutionStatus.EXACT,
            asset_id="dishwasher-bosch-sms6zcw00g",
            confidence=0.95,
            matched_on=["model"],
            filters=SearchFilters(
                asset_id="dishwasher-bosch-sms6zcw00g",
                source_type=SourceType.MANUAL,
            ),
        )

        self.assertEqual(resolution.to_json_dict()["status"], "exact")
        self.assertEqual(
            resolution.to_json_dict()["filters"]["source_type"], "manual"
        )

    def test_error_response_contract_serializes_details(self) -> None:
        error = ErrorResponse(
            code="lancedb_unavailable",
            message="LanceDB table is not available.",
            details={"table": "home_wiki_chunks"},
        )

        self.assertEqual(
            error.to_json_dict(),
            {
                "code": "lancedb_unavailable",
                "message": "LanceDB table is not available.",
                "details": {"table": "home_wiki_chunks"},
            },
        )

    def test_agent_execute_response_serializes_tool_call_plan(self) -> None:
        response = AgentExecuteResponse(
            input="list devices",
            plan=[
                AgentPlanStep(
                    order=1,
                    intent="device_list",
                    tool_call=AgentToolCall(
                        action=AgentAction.LIST_DEVICES,
                        inputs={},
                    ),
                )
            ],
            steps=[
                {
                    "order": 1,
                    "intent": "device_list",
                    "tool_call": {"action": "list_devices", "inputs": {}},
                    "status": AgentStepStatus.SUCCESS,
                    "result": {"devices": []},
                }
            ],
            result={"devices": []},
        )

        serialized = response.to_json_dict()
        self.assertEqual(serialized["plan"][0]["tool_call"]["action"], "list_devices")
        self.assertEqual(serialized["steps"][0]["status"], "success")

    def test_model_normalization_removes_punctuation_and_spacing(self) -> None:
        self.assertEqual(normalize_model_identifier("SMS 6ZCW-00G"), "sms6zcw00g")
        self.assertEqual(normalize_model_identifier("RT_AX88U"), "rtax88u")

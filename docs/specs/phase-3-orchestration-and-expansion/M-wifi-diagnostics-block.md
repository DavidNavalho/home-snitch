# M - WiFi Diagnostics Block

## Summary

Design a separate future block that checks local WiFi/network conditions and recommends whether the current network is suitable for downloads or if another known network may be better.

## Priority

P2. This is outside the critical path for home wiki RAG.

## Dependencies

- A - Project Contracts And Config, for shared config/logging style.
- OS command availability and permissions.

## Can Run In Parallel With

L, after core home wiki work is stable. It should remain isolated from RAG implementation.

## Goals

- Detect current network basics.
- Run lightweight connectivity/latency checks.
- Optionally run a small download test.
- Return actionable status and recommendation.
- Expose as independent CLI and later API endpoint.

## Non-Goals

- No automatic WiFi switching in MVP.
- No router admin login.
- No destructive network changes.
- No dependency on home wiki LanceDB/search.

## Files And Modules

- `homewiki/wifi_diagnostics.py`
- `scripts/wifi_diagnose.py`

## CLI Contract

```bash
python scripts/wifi_diagnose.py
python scripts/wifi_diagnose.py --download-test-url https://example.com/small-file
python scripts/wifi_diagnose.py --json
```

## Python Contract

```python
diagnose_wifi(
    download_test_url: str | None = None,
    timeout_seconds: int = 10,
) -> WifiDiagnosticResult
```

## Result Schema

Fields:

- `current_ssid: str | None`
- `interface: str | None`
- `gateway_reachable: bool | None`
- `dns_ok: bool | None`
- `latency_ms: float | None`
- `packet_loss_percent: float | None`
- `download_mbps: float | None`
- `observations: list[str]`
- `recommendation: str`
- `severity: ok | degraded | bad | unknown`

## Data Collection Ideas

macOS examples:

- `networksetup -getairportnetwork <interface>`
- `airport -I` if available
- `route -n get default`
- `ping -c 3 <gateway>`
- DNS lookup to a known host
- optional HTTP download timing

Linux examples:

- `iwgetid`
- `nmcli`
- `ip route`
- `ping`

Implementation should detect OS and command availability.

## Recommendation Rules

Initial deterministic rules:

- If DNS fails but gateway works: recommend DNS/network issue.
- If gateway ping fails: current network likely unusable.
- If latency high or packet loss > 5%: network degraded.
- If download test is below configured threshold: avoid large downloads.
- If checks cannot run: severity `unknown` with observations.

## Error Handling

- Missing OS commands should produce observations, not crashes.
- Permission failures should be reported clearly.
- Download test should be optional and timeout-bound.

## Testing Strategy

### Deterministic Tests

- Mock command outputs for healthy WiFi.
- Mock command outputs for high packet loss.
- Mock missing DNS.
- Mock missing command.
- Mock download test below threshold.
- Verify JSON output schema.

### Live Tests

Run only when explicitly requested because results depend on environment:

```bash
RUN_NETWORK_TESTS=1 pytest
```

### LLM-Assisted Evaluation

Optional. Give evaluator diagnostic JSON. Expected result: evaluator agrees the recommendation follows observations and does not claim unavailable measurements.

## Expected Scenario Results

### Scenario M1 - Healthy Network

Mock:

- Gateway reachable.
- DNS OK.
- Latency 20 ms.
- Packet loss 0%.
- Download 80 Mbps.

Expected:

- Severity `ok`.
- Recommendation says current WiFi is suitable for downloads.

### Scenario M2 - Degraded Network

Mock:

- Gateway reachable.
- DNS OK.
- Latency 250 ms.
- Packet loss 8%.
- Download 2 Mbps.

Expected:

- Severity `degraded` or `bad`.
- Recommendation says avoid large downloads or try another network.
- Observations include packet loss and low throughput.

### Scenario M3 - Unknown Environment

Mock:

- SSID command unavailable.
- Ping command unavailable.
- No download URL supplied.

Expected:

- Severity `unknown`.
- Recommendation says diagnostics are incomplete.
- No crash.

## Acceptance Criteria

- WiFi block is standalone.
- No network changes are made.
- Diagnostics are structured and testable with mocked command outputs.


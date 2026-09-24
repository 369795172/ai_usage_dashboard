# Test Design

This project has three test surfaces: Python aggregation/service logic, host-side firmware logic mirrors, and optional real hardware checks.

## Python Tests

Run from the repo root:

```bash
.venv/bin/python -m pytest tests/ -v
```

These tests should not require real provider credentials or network calls. They cover token aggregation, pricing logic, FastAPI contract behavior, local cache fallback behavior, and GLM timestamp parsing.

OpenRouter coverage (all monkeypatched, no network):

- `tests/test_openrouter_usage.py`: parse/fetch/export of the key spend window (`limit - limit_remaining`, never lifetime `usage`)
- `tests/test_auto_usage.py`: `OPENROUTER_API_KEY` wiring in `build_latest_dashboard_payload` (key present appends snapshot; key absent skips export; export error still builds other quotas)

Gemini Developer API spend (local JSONL, no network, no `GEMINI_API_KEY`):

- `tests/test_gemini_api_usage.py`: Veo/image price table, today vs 30d window, failed rows skipped, missing ledger returns empty
- `tests/test_auto_usage.py`: ledger export is appended; export error still builds other quotas; stdout prints USD not a fake 0% bar
- `tests/test_dashboard_models.py`: optional `usage_usd` / `remaining_usd` on `QuotaSnapshot` and `AutomationQuotaSnapshot` (default `None` so old payloads validate; every field has a description)
- `tests/test_local_display_service.py`: `GET /api/v1/quotas` passes USD fields through when present and emits `null` when absent

Ark Seedance spend (local JSONL, no network, no `ARK_API_KEY`):

- `tests/test_ark_api_usage.py`: 2.0/fast CNY table, tokens override, today vs 30d, failed rows skipped, missing ledger still emits ¥0
- `tests/test_auto_usage.py`: ledger export is appended; export error still builds other quotas; stdout prints ¥ not a fake 0% bar
- `tests/test_dashboard_models.py`: optional `usage_cny` / `remaining_cny` (default `None`)
- `tests/test_local_display_service.py`: `GET /api/v1/quotas` passes CNY fields through as `null` when absent

## Service Smoke Test

Start the local service:

```bash
scripts/ai-usage-service
```

Health check:

```bash
curl -s http://127.0.0.1:7995/health
```

Expected shape:

- `status=ok`
- `service=ai_usage_dashboard`

Display update check:

```bash
curl -s -X POST http://127.0.0.1:7995/api/v1/display/update \
  -H 'Content-Type: application/json' \
  -d '{"reason":"force_button","view":"7d","device_id":"example-device"}'
```

Expected shape:

- top-level keys: `meta`, `summary`, `daily`
- `meta.generated_at` advances after a successful refresh instead of staying on an old cached timestamp

Quota automation check:

```bash
curl -s http://127.0.0.1:7995/api/v1/quotas
```

Expected shape:

- top-level keys: `generated_at`, `quotas`
- each quota contains `provider`, `label`, `used_percentage`, and `remaining_percentage`
- `used_percentage + remaining_percentage == 100`
- reset fields are `next_reset_time_ms` and `next_reset_iso`, or null when unavailable
- GET reads memory or `token_usage_eink.json` and never forces provider refreshes
- when neither cache exists, the endpoint returns `generated_at=null` and `quotas=[]`

The first full dashboard request may read real local usage sources if no cache
exists. The quota endpoint is cache-only. Use service smoke tests only in a
private environment.

## Host-Side Firmware Logic Tests

The Python tests mirror firmware pure logic instead of simulating ESP32 hardware. They cover:

- white button stays local-only
- green button triggers fetch
- auto-update time window logic
- 7D / 30D view toggle semantics
- display window slicing
- ISO date label compaction

## Firmware Compile Check

If `arduino-cli` and the ESP32 board package are installed, compile the E1002 sketch after meaningful firmware changes:

```bash
arduino-cli compile \
  --clean \
  --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi,FlashMode=qio,UploadSpeed=115200,USBMode=default,CDCOnBoot=cdc \
  eink/e1002/e1002.ino
```

This catches header/include mistakes, symbol visibility mistakes, sketch size regressions, and Arduino API misuse. It is the E1002 configuration verified on 2026-07-21 with ESP32 core `3.3.10`; do not replace Arduino's bundled `ctags 5.8-arduino11` with Homebrew `universal-ctags`, because Arduino's sketch preprocessor requires the bundled output format.

## Manual Hardware Smoke Tests

These require a real E1002 device:

- Green button waits for fresh data and redraws the dashboard.
- White button only switches 7D / 30D view and redraws from cached data.
- Timer wake only fetches during the configured daytime update window.
- If POST refresh fails, device falls back to cached JSON or last-good screen state.
- If Wi-Fi fails, device keeps stale data when available instead of blanking the screen.

## Privacy Checks

Before public publication, run:

```bash
git check-ignore .env token_usage_eink.json token_usage_dashboard.png usage.json cursor.csv glm.json update.log antigravity_sync_metadata.json tmp/example.txt
```

Also scan public files for fixed LAN IPs, personal absolute paths, private deployment hostnames, old workspace paths, and secret-manager references. The scan should produce no matches in public files.

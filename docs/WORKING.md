# Working Notes

## Changelog

### 2026-09-01

- Added a local Gemini Developer API spend collector (`gemini_api_usage.py`). Google does not expose dollar spend on `GEMINI_API_KEY`; the dashboard prices a gitignored JSONL ledger (Veo per second, image per count) from the published paid-tier table and emits `usage_usd` quota rows distinct from the Gemini token bucket.
- Added a local Volcengine Ark Seedance spend collector (`ark_api_usage.py`). Bearer `ARK_API_KEY` cannot query GetInferenceUsage; the dashboard prices a gitignored JSONL ledger in CNY (720p token-density table, 2026-09-01) and emits `usage_cny` rows. Empty ledger still shows ¥0 so the row is visible before the first job.

### 2026-07-21

- Corrected E1002 Arduino guidance from `ESP32S3 Dev Module` to the hardware-verified `XIAO_ESP32S3` configuration: ESP32 core `3.3.10`, OPI PSRAM, QIO, `BOARD_SCREEN_COMBO 521`, and 115200 upload speed.
- Recorded that Homebrew `universal-ctags` is incompatible with Arduino sketch prototype generation. Restore Arduino's bundled `ctags 5.8-arduino11` and use `--clean` after a replacement.

### 2026-05-25

- Began public-repo scaffold pass.
- Added `.env.example`, `AGENTS.md`, `pyproject.toml`, `scripts/`, and repo-local root skill.
- Moved E1002 local service URL and device ID expectations into private `secrets.h` configuration via the public `secrets.h.example` template.
- Rewrote public README and test docs to remove private workspace paths, fixed LAN IPs, and private deployment assumptions.

## Lessons Learned

- Generated usage files are private artifacts, even when aggregated. Keep `usage.json`, `cursor.csv`, `glm.json`, `token_usage_dashboard.png`, `token_usage_eink.json`, and logs ignored.
- The canonical skill should live inside the project repo. Global workspace skill entries should point to it rather than duplicating content.
- Keep local hardware/network configuration in ignored files. Public firmware should rely on `secrets.h.example` placeholders.

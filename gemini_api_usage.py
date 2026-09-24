"""Estimate Gemini Developer API spend from a local JSONL ledger.

Google does not expose dollar spend on a GEMINI_API_KEY. AI Studio Usage and
Cloud Billing need a browser session or GCP export. This collector prices
rootgrove-owned calls (Veo seconds, image counts) from the published Gemini
API paid-tier table and emits unified QuotaSnapshot rows with usage_usd.

Ledger path resolution (first match):

1. ``GEMINI_API_LEDGER_PATH``
2. ``<rootgrove>/logs/gemini_api_ledger.jsonl`` when this clone lives under rootgrove
3. ``./gemini_api_ledger.jsonl`` next to this file

Each line is one JSON object. Unknown keys are ignored::

    {"ts": "2026-09-01T18:22:00+08:00", "model": "veo-3.1-generate-preview",
     "kind": "video", "seconds": 8, "resolution": "720p", "audio": true,
     "success": true, "source": "adhoc/dong_skeletal_rhythm_broll"}

``cost_usd`` on a row overrides the price table. Failed rows (``success: false``)
are skipped. Optional ``GEMINI_API_BUDGET_USD`` fills remaining_usd / percentage
on the 30-day snapshot only.

Prices captured 2026-09-01 from https://ai.google.dev/gemini-api/docs/pricing
(Veo 3.1 with-audio default; Gemini 3.1 Flash Image 1K equivalent).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
LEDGER_FILENAME = 'gemini_api_ledger.jsonl'
PRICING_AS_OF = '2026-09-01'
PROVIDER = 'gemini_api'

# Veo 3.1 paid tier, USD per output second, with audio (API default).
_VEO_AUDIO_USD_PER_SEC = {
    'standard': {'720p': 0.40, '1080p': 0.40, '4k': 0.60},
    'fast': {'720p': 0.10, '1080p': 0.12, '4k': 0.30},
    'lite': {'720p': 0.05, '1080p': 0.08},
}

# Gemini 3.1 Flash Image paid-tier equivalent USD per output image.
_IMAGE_USD = {
    '0.5K': 0.045,
    '1K': 0.067,
    '2K': 0.101,
    '4K': 0.151,
}


def default_ledger_path() -> Path:
    env = os.environ.get('GEMINI_API_LEDGER_PATH', '').strip()
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent
    rootgrove = here.parent.parent
    if (rootgrove / 'tools' / 'web_dashboard').is_dir():
        return rootgrove / 'logs' / LEDGER_FILENAME
    return here / LEDGER_FILENAME


def _parse_ts(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def _veo_tier(model: str) -> str | None:
    lowered = model.lower()
    if 'veo' not in lowered:
        return None
    if 'lite' in lowered:
        return 'lite'
    if 'fast' in lowered:
        return 'fast'
    return 'standard'


def _norm_resolution(raw: object) -> str:
    text = str(raw or '720p').strip().lower().replace(' ', '')
    if text in {'4k', '2160p', '2160'}:
        return '4k'
    if text in {'1080p', '1080', 'fhd'}:
        return '1080p'
    return '720p'


def _norm_image_size(raw: object) -> str:
    text = str(raw or '1K').strip().upper().replace(' ', '')
    if text in _IMAGE_USD:
        return text
    return '1K'


def estimate_cost(event: dict[str, Any]) -> float | None:
    """Return USD for one successful event, or None when it cannot be priced."""
    explicit = event.get('cost_usd')
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        return float(explicit)

    model = str(event.get('model') or '')
    kind = str(event.get('kind') or '').lower()
    if kind == 'video' or _veo_tier(model):
        tier = _veo_tier(model)
        if tier is None:
            return None
        seconds = event.get('seconds')
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
            return None
        res = _norm_resolution(event.get('resolution'))
        table = _VEO_AUDIO_USD_PER_SEC[tier]
        rate = table.get(res)
        if rate is None:
            return None
        return round(float(seconds) * rate, 6)

    if kind == 'image' or 'image' in model.lower():
        images = event.get('images', 1)
        if not isinstance(images, (int, float)) or isinstance(images, bool) or images <= 0:
            return None
        price = _IMAGE_USD[_norm_image_size(event.get('image_size'))]
        return round(float(images) * price, 6)
    return None


def load_ledger_events(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            events.append(row)
    return events


def append_ledger_event(event: dict[str, Any], path: Path | None = None) -> Path:
    """Append one JSONL row. Never raises to the caller of image/video tools."""
    target = path or default_ledger_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    row = dict(event)
    row.setdefault('ts', datetime.now(tz=TZ).isoformat(timespec='seconds'))
    row.setdefault('success', True)
    with target.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    return target


def _sum_spend(events: list[dict[str, Any]], start: datetime, end: datetime) -> float:
    total = 0.0
    for event in events:
        if event.get('success') is False:
            continue
        ts = _parse_ts(event.get('ts'))
        if ts is None or ts < start or ts >= end:
            continue
        cost = estimate_cost(event)
        if cost is None:
            continue
        total += cost
    return round(total, 4)


def _budget_usd() -> float | None:
    raw = os.environ.get('GEMINI_API_BUDGET_USD', '').strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def parse_gemini_api_quota(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    budget_usd: float | None = None,
) -> list[dict[str, Any]]:
    moment = now or datetime.now(tz=TZ)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=TZ)
    moment = moment.astimezone(TZ)
    today_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = today_start - timedelta(days=29)
    tomorrow = today_start + timedelta(days=1)

    today = _sum_spend(events, today_start, tomorrow)
    month = _sum_spend(events, window_start, tomorrow)

    today_row: dict[str, Any] = {
        'provider': PROVIDER,
        'label': 'today',
        'usage_usd': today,
    }
    month_row: dict[str, Any] = {
        'provider': PROVIDER,
        'label': '30d',
        'usage_usd': month,
    }
    cap = budget_usd if budget_usd is not None else _budget_usd()
    if cap is not None:
        remaining = max(0.0, round(cap - month, 4))
        month_row['remaining_usd'] = remaining
        month_row['percentage'] = max(0, min(100, int(round(month / cap * 100))))
    return [today_row, month_row]


def export_gemini_api_quota(
    ledger_path: Path | str | None = None,
    *,
    now: datetime | None = None,
    budget_usd: float | None = None,
) -> list[dict[str, Any]]:
    path = Path(ledger_path) if ledger_path else default_ledger_path()
    events = load_ledger_events(path)
    if not events:
        return []
    return parse_gemini_api_quota(events, now=now, budget_usd=budget_usd)

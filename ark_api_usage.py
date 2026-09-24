"""Estimate Volcengine Ark video spend from a local JSONL ledger.

GetInferenceUsage / 费用中心账单要 IAM AK/SK，Bearer ``ARK_API_KEY`` 只能打数据面。
This collector prices rootgrove-owned Seedance jobs from the published CNY
token table and emits QuotaSnapshot rows with ``usage_cny``.

Ledger path resolution (first match):

1. ``ARK_API_LEDGER_PATH``
2. ``<rootgrove>/logs/ark_api_ledger.jsonl`` when this clone lives under rootgrove
3. ``./ark_api_ledger.jsonl`` next to this file

Each line is one JSON object::

    {"ts": "2026-09-01T21:00:00+08:00", "model": "doubao-seedance-2-0-260128",
     "kind": "video", "seconds": 10, "resolution": "720p", "video_input": false,
     "success": true, "source": "adhoc/dong_skeletal_rhythm_broll"}

``cost_cny`` on a row overrides the table. ``tokens`` uses the CNY/1M rate.
Failed rows are skipped. Empty or missing ledger still emits today/30d at ¥0
so the dashboard row is visible before the first job.

Optional ``ARK_API_BUDGET_CNY`` fills remaining_cny / percentage on 30d.

Prices captured 2026-09-01 from public Ark Seedance 2.0/2.0-fast tables:
720p 15s ≈ 308880 output tokens. Text/image-to-video (no video input) is
46 CNY / 1M tokens (fast: 37). With video input: 28 (fast: 22).
Resolution other than 720p still uses this 720p token density unless the
row carries ``tokens`` or ``cost_cny``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Asia/Shanghai')
LEDGER_FILENAME = 'ark_api_ledger.jsonl'
PRICING_AS_OF = '2026-09-01'
PROVIDER = 'ark_api'

_TOKENS_PER_SEC_720P = 308_880 / 15
_CNY_PER_MTOK = {
    '2.0': {'t2v': 46.0, 'with_video': 28.0},
    '2.0-fast': {'t2v': 37.0, 'with_video': 22.0},
}


def default_ledger_path() -> Path:
    env = os.environ.get('ARK_API_LEDGER_PATH', '').strip()
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


def _seedance_tier(model: str) -> str | None:
    lowered = model.lower().replace('_', '-')
    if 'seedance' not in lowered:
        return None
    if 'fast' in lowered:
        return '2.0-fast'
    return '2.0'


def _rate_cny_per_mtok(tier: str, video_input: bool) -> float:
    table = _CNY_PER_MTOK[tier]
    return table['with_video'] if video_input else table['t2v']


def estimate_cost_cny(event: dict[str, Any]) -> float | None:
    explicit = event.get('cost_cny')
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        return float(explicit)

    model = str(event.get('model') or '')
    tier = _seedance_tier(model)
    if tier is None:
        return None
    video_input = bool(event.get('video_input'))
    rate = _rate_cny_per_mtok(tier, video_input)

    tokens = event.get('tokens')
    if isinstance(tokens, (int, float)) and not isinstance(tokens, bool) and tokens > 0:
        return round(float(tokens) / 1_000_000 * rate, 6)

    seconds = event.get('seconds')
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
        return None
    return round(float(seconds) * _TOKENS_PER_SEC_720P / 1_000_000 * rate, 6)


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
        cost = estimate_cost_cny(event)
        if cost is None:
            continue
        total += cost
    return round(total, 4)


def _budget_cny() -> float | None:
    raw = os.environ.get('ARK_API_BUDGET_CNY', '').strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def parse_ark_api_quota(
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    budget_cny: float | None = None,
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
        'usage_cny': today,
    }
    month_row: dict[str, Any] = {
        'provider': PROVIDER,
        'label': '30d',
        'usage_cny': month,
    }
    cap = budget_cny if budget_cny is not None else _budget_cny()
    if cap is not None:
        remaining = max(0.0, round(cap - month, 4))
        month_row['remaining_cny'] = remaining
        month_row['percentage'] = max(0, min(100, int(round(month / cap * 100))))
    return [today_row, month_row]


def export_ark_api_quota(
    ledger_path: Path | str | None = None,
    *,
    now: datetime | None = None,
    budget_cny: float | None = None,
) -> list[dict[str, Any]]:
    path = Path(ledger_path) if ledger_path else default_ledger_path()
    events = load_ledger_events(path)
    return parse_ark_api_quota(events, now=now, budget_cny=budget_cny)

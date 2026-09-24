from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gemini_api_usage import (
    append_ledger_event,
    estimate_cost,
    export_gemini_api_quota,
    parse_gemini_api_quota,
)

TZ = ZoneInfo('Asia/Shanghai')
NOW = datetime(2026, 9, 1, 20, 40, tzinfo=TZ)


def _event(**kwargs):
    row = {
        'ts': '2026-09-01T18:22:00+08:00',
        'model': 'veo-3.1-generate-preview',
        'kind': 'video',
        'seconds': 8,
        'resolution': '720p',
        'success': True,
    }
    row.update(kwargs)
    return row


def test_estimate_veo_standard_720p_with_audio():
    assert estimate_cost(_event()) == 3.2


def test_estimate_veo_fast_and_lite():
    fast = estimate_cost(_event(model='veo-3.1-fast-generate-preview'))
    lite = estimate_cost(_event(model='veo-3.1-lite-generate-preview'))
    assert fast == 0.8
    assert lite == 0.4


def test_estimate_image_1k_flash():
    cost = estimate_cost(
        {
            'model': 'gemini-3.1-flash-image-preview',
            'kind': 'image',
            'images': 2,
            'image_size': '1K',
        }
    )
    assert cost == 0.134


def test_estimate_explicit_cost_overrides_table():
    assert estimate_cost(_event(cost_usd=1.23)) == 1.23


def test_estimate_unknown_model_returns_none():
    assert estimate_cost({'model': 'mystery', 'kind': 'other', 'seconds': 8}) is None


def test_parse_splits_today_and_30d(tmp_path: Path):
    events = [
        _event(ts='2026-09-01T10:00:00+08:00', seconds=8),
        _event(
            ts='2026-08-10T10:00:00+08:00',
            model='veo-3.1-fast-generate-preview',
            seconds=8,
        ),
        _event(ts='2026-07-01T10:00:00+08:00', seconds=8),
        _event(ts='2026-09-01T11:00:00+08:00', success=False, seconds=8),
    ]
    snapshots = parse_gemini_api_quota(events, now=NOW)
    assert snapshots[0]['label'] == 'today'
    assert snapshots[0]['usage_usd'] == 3.2
    assert 'percentage' not in snapshots[0]
    assert snapshots[1]['label'] == '30d'
    assert snapshots[1]['usage_usd'] == 4.0
    assert 'remaining_usd' not in snapshots[1]


def test_parse_applies_budget_only_to_30d():
    snapshots = parse_gemini_api_quota(
        [_event()], now=NOW, budget_usd=10.0
    )
    month = snapshots[1]
    assert month['remaining_usd'] == 6.8
    assert month['percentage'] == 32


def test_export_missing_file_returns_empty(tmp_path: Path):
    assert export_gemini_api_quota(tmp_path / 'missing.jsonl') == []


def test_export_reads_jsonl(tmp_path: Path):
    ledger = tmp_path / 'gemini_api_ledger.jsonl'
    ledger.write_text(json.dumps(_event()) + '\nnot-json\n', encoding='utf-8')
    snapshots = export_gemini_api_quota(ledger, now=NOW)
    assert snapshots[0]['usage_usd'] == 3.2
    assert snapshots[0]['provider'] == 'gemini_api'


def test_append_ledger_event_creates_file(tmp_path: Path):
    path = tmp_path / 'nested' / 'ledger.jsonl'
    append_ledger_event(_event(source='test'), path=path)
    lines = path.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row['source'] == 'test'
    assert row['success'] is True

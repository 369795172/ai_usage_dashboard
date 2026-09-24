from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ark_api_usage import (
    append_ledger_event,
    estimate_cost_cny,
    export_ark_api_quota,
    parse_ark_api_quota,
)

TZ = ZoneInfo('Asia/Shanghai')
NOW = datetime(2026, 9, 1, 21, 30, tzinfo=TZ)
# 10s × 308880/15 tokens × 46 CNY / 1M
CNY_10S_T2V = 9.47232
CNY_10S_FAST = 7.61904
CNY_10S_WITH_VIDEO = 5.76576


def _event(**kwargs):
    row = {
        'ts': '2026-09-01T21:00:00+08:00',
        'model': 'doubao-seedance-2-0-260128',
        'kind': 'video',
        'seconds': 10,
        'resolution': '720p',
        'video_input': False,
        'success': True,
    }
    row.update(kwargs)
    return row


def test_estimate_seedance_2_0_720p_t2v():
    assert estimate_cost_cny(_event()) == CNY_10S_T2V


def test_estimate_seedance_fast_and_with_video():
    fast = estimate_cost_cny(_event(model='doubao-seedance-2-0-fast-260128'))
    with_video = estimate_cost_cny(_event(video_input=True))
    assert fast == CNY_10S_FAST
    assert with_video == CNY_10S_WITH_VIDEO


def test_estimate_tokens_overrides_seconds():
    cost = estimate_cost_cny(_event(tokens=308_880, seconds=99))
    assert cost == 14.20848


def test_estimate_explicit_cost_overrides_table():
    assert estimate_cost_cny(_event(cost_cny=1.23)) == 1.23


def test_estimate_unknown_model_returns_none():
    assert estimate_cost_cny({'model': 'mystery', 'seconds': 10}) is None


def test_parse_splits_today_and_30d():
    events = [
        _event(ts='2026-09-01T10:00:00+08:00'),
        _event(
            ts='2026-08-10T10:00:00+08:00',
            model='doubao-seedance-2-0-fast-260128',
        ),
        _event(ts='2026-07-01T10:00:00+08:00'),
        _event(ts='2026-09-01T11:00:00+08:00', success=False),
    ]
    snapshots = parse_ark_api_quota(events, now=NOW)
    assert snapshots[0]['label'] == 'today'
    assert snapshots[0]['usage_cny'] == round(CNY_10S_T2V, 4)
    assert 'percentage' not in snapshots[0]
    assert snapshots[1]['label'] == '30d'
    assert snapshots[1]['usage_cny'] == round(CNY_10S_T2V + CNY_10S_FAST, 4)
    assert 'remaining_cny' not in snapshots[1]


def test_parse_empty_emits_zero_rows():
    snapshots = parse_ark_api_quota([], now=NOW)
    assert snapshots[0]['usage_cny'] == 0.0
    assert snapshots[1]['usage_cny'] == 0.0
    assert snapshots[0]['provider'] == 'ark_api'


def test_parse_applies_budget_only_to_30d():
    snapshots = parse_ark_api_quota([_event()], now=NOW, budget_cny=20.0)
    month = snapshots[1]
    used = round(CNY_10S_T2V, 4)
    assert month['remaining_cny'] == round(20.0 - used, 4)
    assert month['percentage'] == 47


def test_export_missing_file_still_emits_zeros(tmp_path: Path):
    snapshots = export_ark_api_quota(tmp_path / 'missing.jsonl', now=NOW)
    assert snapshots[0]['usage_cny'] == 0.0
    assert snapshots[1]['usage_cny'] == 0.0


def test_export_reads_jsonl(tmp_path: Path):
    ledger = tmp_path / 'ark_api_ledger.jsonl'
    ledger.write_text(json.dumps(_event()) + '\nnot-json\n', encoding='utf-8')
    snapshots = export_ark_api_quota(ledger, now=NOW)
    assert snapshots[0]['usage_cny'] == round(CNY_10S_T2V, 4)
    assert snapshots[0]['provider'] == 'ark_api'


def test_append_ledger_event_creates_file(tmp_path: Path):
    path = tmp_path / 'nested' / 'ledger.jsonl'
    append_ledger_event(_event(source='test'), path=path)
    lines = path.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row['source'] == 'test'
    assert row['success'] is True

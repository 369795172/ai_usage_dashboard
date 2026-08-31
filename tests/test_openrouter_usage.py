from __future__ import annotations

import io
import json
import urllib.error

import pytest

from openrouter_usage import (
    OpenRouterKeyResponse,
    export_openrouter_quota,
    fetch_openrouter_key,
    parse_openrouter_quota,
)


def _payload(
    limit: float | None = 10.0,
    limit_remaining: float | None = 7.0,
    limit_reset: str | None = 'weekly',
    usage: float = 99.5,
) -> OpenRouterKeyResponse:
    return {
        'data': {
            'label': 'sk-or-v1-test',
            'usage': usage,
            'limit': limit,
            'limit_remaining': limit_remaining,
            'limit_reset': limit_reset,
            'usage_daily': 1.25,
            'usage_weekly': 3.0,
            'usage_monthly': 40.75,
            'is_free_tier': False,
        }
    }


def test_parse_weekly_response_uses_window_spend_not_lifetime():
    snapshot = parse_openrouter_quota(_payload())
    assert snapshot == {
        'provider': 'openrouter',
        'label': 'Weekly Spend',
        'percentage': 30,
        'usage_usd': 3.0,
        'remaining_usd': 7.0,
    }
    # lifetime usage 99.5 must never leak into the window spend fields
    assert snapshot is not None
    assert snapshot['usage_usd'] == pytest.approx(3.0)


def test_parse_float_fields_are_floats():
    snapshot = parse_openrouter_quota(_payload(limit=10, limit_remaining=10))
    assert snapshot is not None
    assert isinstance(snapshot['usage_usd'], float)
    assert isinstance(snapshot['remaining_usd'], float)


def test_parse_period_labels_daily_and_monthly():
    daily = parse_openrouter_quota(_payload(limit_reset='daily'))
    monthly = parse_openrouter_quota(_payload(limit_reset='monthly'))
    assert daily is not None and daily['label'] == 'Daily Spend'
    assert monthly is not None and monthly['label'] == 'Monthly Spend'


def test_parse_unknown_reset_falls_back_to_plain_spend():
    unknown = parse_openrouter_quota(_payload(limit_reset='fortnightly'))
    missing = parse_openrouter_quota(_payload(limit_reset=None))
    assert unknown is not None and unknown['label'] == 'Spend'
    assert missing is not None and missing['label'] == 'Spend'


def test_parse_zero_spend():
    snapshot = parse_openrouter_quota(_payload(limit=10, limit_remaining=10))
    assert snapshot is not None
    assert snapshot['percentage'] == 0
    assert snapshot['usage_usd'] == pytest.approx(0.0)
    assert snapshot['remaining_usd'] == pytest.approx(10.0)


def test_parse_clamps_over_100_percent():
    snapshot = parse_openrouter_quota(_payload(limit=10, limit_remaining=-2))
    assert snapshot is not None
    assert snapshot['percentage'] == 100
    assert snapshot['usage_usd'] == pytest.approx(12.0)
    assert snapshot['remaining_usd'] == pytest.approx(-2.0)


def test_parse_null_limit_returns_none():
    assert parse_openrouter_quota(_payload(limit=None)) is None


def test_parse_zero_limit_returns_none():
    assert parse_openrouter_quota(_payload(limit=0)) is None


def test_parse_missing_limit_remaining_returns_none():
    payload = _payload()
    del payload['data']['limit_remaining']
    assert parse_openrouter_quota(payload) is None


def test_parse_accepts_flat_response_without_data_wrapper():
    flat = dict(_payload()['data'])
    snapshot = parse_openrouter_quota(flat)
    assert snapshot is not None
    assert snapshot['provider'] == 'openrouter'
    assert snapshot['percentage'] == 30


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_sends_bearer_header(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen['auth'] = request.get_header('Authorization')
        seen['url'] = request.full_url
        seen['method'] = request.get_method()
        return _FakeResponse(_payload())

    monkeypatch.setattr('openrouter_usage.urllib.request.urlopen', fake_urlopen)
    data = fetch_openrouter_key('sk-test-key')
    assert seen['auth'] == 'Bearer sk-test-key'
    assert seen['url'] == 'https://openrouter.ai/api/v1/key'
    assert seen['method'] == 'GET'
    assert data['data']['limit'] == 10.0


def test_fetch_retries_transient_network_errors(monkeypatch):
    calls = {'n': 0, 'sleeps': 0}

    def fake_sleep(seconds):
        calls['sleeps'] += 1

    def fake_urlopen(request, timeout=None):
        calls['n'] += 1
        if calls['n'] < 3:
            raise OSError('SSL: UNEXPECTED_EOF_WHILE_READING')
        return _FakeResponse(_payload())

    monkeypatch.setattr('openrouter_usage.urllib.request.urlopen', fake_urlopen)
    monkeypatch.setattr('openrouter_usage.time.sleep', fake_sleep)
    data = fetch_openrouter_key('k', attempts=3)
    assert data['data']['limit_remaining'] == 7.0
    assert calls['n'] == 3
    assert calls['sleeps'] == 2


def test_fetch_raises_after_exhausted_retries(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise OSError('connection reset')

    monkeypatch.setattr('openrouter_usage.urllib.request.urlopen', fake_urlopen)
    monkeypatch.setattr('openrouter_usage.time.sleep', lambda s: None)
    with pytest.raises(RuntimeError, match='after 3 attempts'):
        fetch_openrouter_key('k', attempts=3)


def test_fetch_http_error_not_retried_and_key_not_leaked(monkeypatch):
    calls = {'n': 0}

    def fake_urlopen(request, timeout=None):
        calls['n'] += 1
        raise urllib.error.HTTPError(
            'url', 401, 'Unauthorized', {}, io.BytesIO(b'')
        )

    monkeypatch.setattr('openrouter_usage.urllib.request.urlopen', fake_urlopen)
    monkeypatch.setattr('openrouter_usage.time.sleep', lambda s: None)
    with pytest.raises(RuntimeError, match='HTTP 401') as excinfo:
        fetch_openrouter_key('sk-secret-key', attempts=3)
    assert calls['n'] == 1
    assert 'sk-secret-key' not in str(excinfo.value)


def test_export_returns_snapshot_list(monkeypatch):
    monkeypatch.setattr(
        'openrouter_usage.fetch_openrouter_key', lambda api_key: _payload()
    )
    snapshots = export_openrouter_quota('k')
    assert len(snapshots) == 1
    assert snapshots[0]['provider'] == 'openrouter'
    assert snapshots[0]['label'] == 'Weekly Spend'


def test_export_returns_empty_when_unlimited(monkeypatch):
    monkeypatch.setattr(
        'openrouter_usage.fetch_openrouter_key', lambda api_key: _payload(limit=None)
    )
    assert export_openrouter_quota('k') == []

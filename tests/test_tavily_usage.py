from __future__ import annotations

import urllib.error

import pytest

from tavily_usage import fetch_tavily_usage, parse_tavily_quota


def _sample(plan_usage: int = 3551, plan_limit: int = 4000) -> dict:
    return {
        'key': {
            'usage': plan_usage,
            'limit': None,
            'search_usage': 1488,
            'crawl_usage': 0,
            'extract_usage': 35,
            'map_usage': 0,
            'research_usage': 2028,
        },
        'account': {
            'current_plan': 'Project',
            'plan_usage': plan_usage,
            'plan_limit': plan_limit,
            'search_usage': 1488,
            'crawl_usage': 0,
            'extract_usage': 35,
            'map_usage': 0,
            'research_usage': 2028,
            'paygo_usage': 0,
            'paygo_limit': None,
        },
    }


def test_parse_normal_response():
    snapshot = parse_tavily_quota(_sample())
    assert snapshot == {
        'provider': 'tavily',
        'label': 'Credits',
        'percentage': 89,
        'usage': 3551,
        'remaining': 449,
    }


def test_parse_clamps_over_100_percent():
    snapshot = parse_tavily_quota(_sample(plan_usage=4300, plan_limit=4000))
    assert snapshot is not None
    assert snapshot['percentage'] == 100
    assert snapshot['remaining'] == -300


def test_parse_zero_usage():
    snapshot = parse_tavily_quota(_sample(plan_usage=0, plan_limit=1000))
    assert snapshot is not None
    assert snapshot['percentage'] == 0
    assert snapshot['usage'] == 0
    assert snapshot['remaining'] == 1000


def test_parse_null_plan_limit_returns_none():
    response = _sample()
    response['account']['plan_limit'] = None
    assert parse_tavily_quota(response) is None


def test_parse_zero_plan_limit_returns_none():
    assert parse_tavily_quota(_sample(plan_limit=0)) is None


def test_parse_missing_account_returns_none():
    assert parse_tavily_quota({'key': {'usage': 10, 'limit': 20}}) is None


def test_fetch_retries_transient_network_errors(monkeypatch):
    calls = {'n': 0}

    def fake_sleep(seconds):
        calls['sleeps'] = calls.get('sleeps', 0) + 1

    def fake_urlopen(request, timeout=None):
        calls['n'] += 1
        if calls['n'] < 3:
            raise OSError('SSL: UNEXPECTED_EOF_WHILE_READING')
        return _FakeResponse(_sample())

    class _FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            import json

            return json.dumps(self._payload).encode('utf-8')

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr('tavily_usage.urllib.request.urlopen', fake_urlopen)
    monkeypatch.setattr('tavily_usage.time.sleep', fake_sleep)
    data = fetch_tavily_usage('k', attempts=3)
    assert data['account']['plan_usage'] == 3551
    assert calls['n'] == 3
    assert calls.get('sleeps') == 2


def test_fetch_raises_after_exhausted_retries(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise OSError('connection reset')

    monkeypatch.setattr('tavily_usage.urllib.request.urlopen', fake_urlopen)
    monkeypatch.setattr('tavily_usage.time.sleep', lambda s: None)
    with pytest.raises(RuntimeError, match='after 3 attempts'):
        fetch_tavily_usage('k', attempts=3)


def test_fetch_http_error_not_retried(monkeypatch):
    calls = {'n': 0}

    def fake_urlopen(request, timeout=None):
        calls['n'] += 1
        raise urllib.error.HTTPError(
            'url', 401, 'Unauthorized', {}, None  # type: ignore[arg-type]
        )

    monkeypatch.setattr('tavily_usage.urllib.request.urlopen', fake_urlopen)
    monkeypatch.setattr('tavily_usage.time.sleep', lambda s: None)
    with pytest.raises(RuntimeError, match='HTTP 401'):
        fetch_tavily_usage('k', attempts=3)
    assert calls['n'] == 1

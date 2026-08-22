"""Fetch Tavily credit usage from the Tavily usage API.

GET https://api.tavily.com/usage with the API key as a Bearer token returns
key-level and account-level credit counters for the current billing cycle:

    {"key": {"usage": 3551, "limit": null, "search_usage": 1488, ...},
     "account": {"current_plan": "Project", "plan_usage": 3551,
                 "plan_limit": 4000, "paygo_usage": 0, ...}}

The account block is authoritative for the plan quota because key.limit is
null on plan-billed keys. The API does not expose a reset timestamp, so quota
snapshots carry usage/remaining counts only.

Auth is the API key in TAVILY_API_KEY (never commit real keys).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

TAVILY_USAGE_URL = 'https://api.tavily.com/usage'


def fetch_tavily_usage(api_key: str, timeout: float = 20.0, attempts: int = 3) -> dict[str, Any]:
    request = urllib.request.Request(
        TAVILY_USAGE_URL,
        headers={'Authorization': f'Bearer {api_key}'},
        method='GET',
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:200]
            raise RuntimeError(f'tavily usage HTTP {exc.code}: {detail!r}') from exc
        except OSError as exc:
            if attempt >= attempts:
                raise RuntimeError(f'tavily usage network error after {attempts} attempts: {exc!r}') from exc
            time.sleep(2.0)
    raise AssertionError('unreachable')


def parse_tavily_quota(data: dict[str, Any]) -> dict[str, Any] | None:
    account = data.get('account') or {}
    plan_limit = account.get('plan_limit')
    plan_usage = account.get('plan_usage')
    if not isinstance(plan_limit, (int, float)) or plan_limit <= 0:
        return None
    if not isinstance(plan_usage, (int, float)):
        return None
    percentage = max(0, min(100, int(round(plan_usage / plan_limit * 100))))
    return {
        'provider': 'tavily',
        'label': 'Credits',
        'percentage': percentage,
        'usage': int(plan_usage),
        'remaining': int(plan_limit - plan_usage),
    }


def export_tavily_quota(api_key: str) -> list[dict[str, Any]]:
    """Return unified QuotaSnapshot-shaped list for the plan credit pool."""
    snapshot = parse_tavily_quota(fetch_tavily_usage(api_key))
    return [snapshot] if snapshot else []

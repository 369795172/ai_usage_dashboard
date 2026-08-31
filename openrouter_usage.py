"""Fetch OpenRouter normal-key spend quota from the OpenRouter key API.

GET https://openrouter.ai/api/v1/key with the API key as a Bearer token returns
the current key window counters wrapped in a ``data`` object:

    {"data": {"label": "sk-or-v1-...", "usage": 99.5, "limit": 10,
              "limit_remaining": 7, "limit_reset": "weekly",
              "usage_daily": 1.25, "usage_weekly": 3, "usage_monthly": 40.75}}

``limit``/``limit_remaining`` bound the current spend window, so the window
spend is ``limit - limit_remaining`` (never the lifetime ``usage`` counter).
``limit_reset`` only names the window period in the snapshot label. Keys
without a spend limit report ``limit: null`` and yield no snapshot.

Auth is the API key passed by the caller (never commit real keys).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import TypedDict

OPENROUTER_KEY_URL = 'https://openrouter.ai/api/v1/key'

_PERIOD_PREFIXES = {'daily': 'Daily', 'weekly': 'Weekly', 'monthly': 'Monthly'}


class OpenRouterUsageError(RuntimeError):
    """Fetch failure for the OpenRouter key endpoint (HTTP or network)."""


class OpenRouterKeyData(TypedDict, total=False):
    """Fields of the ``data`` object returned by GET /api/v1/key."""

    label: str
    usage: float
    limit: float | None
    limit_remaining: float | None
    limit_reset: str | None


class OpenRouterKeyResponse(TypedDict, total=False):
    data: OpenRouterKeyData


class QuotaSnapshotDict(TypedDict):
    """Unified QuotaSnapshot shape plus OpenRouter USD spend fields."""

    provider: str
    label: str
    percentage: int
    usage_usd: float
    remaining_usd: float


def _is_number(value: float | int | str | None) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def fetch_openrouter_key(
    api_key: str, timeout: float = 20.0, attempts: int = 3
) -> OpenRouterKeyResponse:
    request = urllib.request.Request(
        OPENROUTER_KEY_URL,
        headers={'Authorization': f'Bearer {api_key}'},
        method='GET',
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data: OpenRouterKeyResponse = json.loads(
                    response.read().decode('utf-8')
                )
                return data
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:200]
            raise OpenRouterUsageError(
                f'openrouter key HTTP {exc.code}: {detail!r}'
            ) from exc
        except OSError as exc:
            if attempt >= attempts:
                raise OpenRouterUsageError(
                    f'openrouter key network error after {attempts} attempts: {exc!r}'
                ) from exc
            time.sleep(2.0)
    raise AssertionError('unreachable')


def _window_label(limit_reset: str | None) -> str:
    prefix = _PERIOD_PREFIXES.get(
        limit_reset.strip().lower() if isinstance(limit_reset, str) else ''
    )
    return f'{prefix} Spend' if prefix else 'Spend'


def parse_openrouter_quota(
    data: OpenRouterKeyResponse,
) -> QuotaSnapshotDict | None:
    raw = data.get('data')
    key_data = raw if isinstance(raw, dict) else data
    limit = key_data.get('limit')
    limit_remaining = key_data.get('limit_remaining')
    if not _is_number(limit) or limit <= 0:
        return None
    if not _is_number(limit_remaining):
        return None
    spend = limit - limit_remaining
    percentage = max(0, min(100, int(round(spend / limit * 100))))
    return {
        'provider': 'openrouter',
        'label': _window_label(key_data.get('limit_reset')),
        'percentage': percentage,
        'usage_usd': float(spend),
        'remaining_usd': float(limit_remaining),
    }


def export_openrouter_quota(api_key: str) -> list[QuotaSnapshotDict]:
    """Return unified QuotaSnapshot-shaped list for the key spend window."""
    snapshot = parse_openrouter_quota(fetch_openrouter_key(api_key))
    return [snapshot] if snapshot else []

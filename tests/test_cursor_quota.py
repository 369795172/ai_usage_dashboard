import auto_usage
from datetime import datetime, timezone


def _summary_body(
    enabled=True,
    percent=30.3948,
    cycle_end='2026-09-03T05:56:00.000Z',
) -> dict:
    return {
        'billingCycleStart': '2026-08-03T05:56:00.000Z',
        'billingCycleEnd': cycle_end,
        'membershipType': 'ultra',
        'individualUsage': {
            'plan': {
                'enabled': enabled,
                'used': 40000,
                'limit': 40000,
                'totalPercentUsed': percent,
            },
            'onDemand': {'enabled': True, 'used': 0, 'limit': 5000},
        },
    }


def test_parse_cursor_usage_summary_rounds_percentage_and_sets_reset():
    snapshots = auto_usage.parse_cursor_usage_summary(_summary_body())
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap['provider'] == 'cursor'
    assert snap['label'] == 'monthly'
    assert snap['percentage'] == 30
    expected_ms = int(datetime(2026, 9, 3, 5, 56, tzinfo=timezone.utc).timestamp() * 1000)
    assert snap['next_reset_time_ms'] == expected_ms
    assert snap['next_reset_iso'].startswith('2026-09-03T')


def test_parse_cursor_usage_summary_skips_disabled_plan():
    assert auto_usage.parse_cursor_usage_summary(_summary_body(enabled=False)) == []


def test_parse_cursor_usage_summary_defaults_missing_percentage_to_zero():
    body = _summary_body()
    body['individualUsage']['plan'].pop('totalPercentUsed')
    snapshots = auto_usage.parse_cursor_usage_summary(body)
    assert snapshots[0]['percentage'] == 0


def test_parse_cursor_usage_summary_tolerates_bad_percentage_and_no_cycle_end():
    body = _summary_body(percent='n/a', cycle_end=None)
    body.pop('billingCycleEnd')
    snapshots = auto_usage.parse_cursor_usage_summary(body)
    assert snapshots[0]['percentage'] == 0
    assert 'next_reset_time_ms' not in snapshots[0]
    assert 'next_reset_iso' not in snapshots[0]


def test_parse_cursor_usage_summary_clamps_out_of_range_percentage():
    snapshots = auto_usage.parse_cursor_usage_summary(_summary_body(percent=104.2))
    assert snapshots[0]['percentage'] == 100

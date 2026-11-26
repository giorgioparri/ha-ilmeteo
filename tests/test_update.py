"""Unit tests for the coordinator's pure update logic (update.py).

Run with:  python tests/test_update.py
No Home Assistant dependency. The coordinator only wires these functions to
HA (scheduling, storage, notifications, reauth); every decision about what to
request, what to show and how to react to each gateway error is made here.
"""
import json
import os
import random
import sys
import types
from datetime import UTC, date, datetime, timedelta, timezone

# update.py imports its siblings relatively (from .client import ...), as
# modules inside an HA integration must. Register the folder as a bare
# "ilmeteo" package so those imports resolve without running __init__.py,
# which needs Home Assistant.
_PKG_DIR = os.path.join(os.path.dirname(__file__), "..", "custom_components", "ilmeteo")
_pkg = types.ModuleType("ilmeteo")
_pkg.__path__ = [_PKG_DIR]
sys.modules.setdefault("ilmeteo", _pkg)

from ilmeteo.client import (  # noqa: E402
    IlMeteoAuthError,
    IlMeteoConnectionError,
    IlMeteoOutOfScope,
    IlMeteoQuotaExceeded,
    IlMeteoRequestError,
    IlMeteoUnrecognizedAuthError,
    parse_daily,
    parse_hourly,
)
from ilmeteo.quota import QuotaTracker  # noqa: E402
from ilmeteo.update import (  # noqa: E402
    ENDPOINT_DAILY,
    ENDPOINT_HOURLY,
    UNRECOGNIZED_AUTH_GRACE,
    Action,
    KeyStatus,
    Notice,
    build_snapshot,
    dew_point,
    plan_update,
    request_window,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
CEST = timezone(timedelta(hours=2))
NOW = datetime(2026, 10, 8, 21, 42, tzinfo=CEST)


def _fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


DAILY = parse_daily(_fixture("api_daily_5658.json"))
HOURLY = parse_hourly(_fixture("api_hourly_5658.json"))


# --- What to request -----------------------------------------------------

def test_request_window_is_today_plus_two_in_italy():
    assert request_window(NOW) == (date(2026, 10, 8), date(2026, 10, 10))


def test_request_window_follows_the_italian_date_not_utc():
    # 22:30 UTC on the 8th is 00:30 on the 9th in Italy.
    late = datetime(2026, 10, 8, 22, 30, tzinfo=UTC)
    assert request_window(late) == (date(2026, 10, 9), date(2026, 10, 11))


# --- Dew point -----------------------------------------------------------

def test_dew_point_known_values():
    # Magnus formula; reference values to 0.1 °C.
    assert round(dew_point(20.0, 50.0), 1) == 9.3
    assert round(dew_point(17.91, 93.0), 1) == 16.8
    assert round(dew_point(0.0, 100.0), 1) == 0.0


def test_dew_point_missing_or_invalid_input():
    assert dew_point(None, 50.0) is None
    assert dew_point(20.0, None) is None
    assert dew_point(20.0, 0.0) is None
    assert dew_point(20.0, -5.0) is None


# --- What to show --------------------------------------------------------

def test_snapshot_at_the_fixture_time():
    snap = build_snapshot(DAILY, HOURLY, NOW)
    assert snap.current.time == datetime(2026, 10, 8, 21, 0, tzinfo=CEST)
    assert round(snap.dew_point, 1) == 16.8
    # Hourly forecast starts at the current slot, past hours dropped.
    assert snap.hourly[0].time == snap.current.time
    assert len(snap.hourly) == 71 - 21
    # Daily forecast starts today.
    assert snap.daily[0].date == date(2026, 10, 8)
    assert len(snap.daily) == 8


def test_snapshot_advances_on_cached_data_without_new_calls():
    # Blocked until midnight: the same downloaded lists, a later "now".
    later = datetime(2026, 10, 9, 10, 15, tzinfo=CEST)
    snap = build_snapshot(DAILY, HOURLY, later)
    assert snap.current.time == datetime(2026, 10, 9, 10, 0, tzinfo=CEST)
    assert snap.daily[0].date == date(2026, 10, 9)
    assert len(snap.daily) == 7


def test_snapshot_past_the_end_of_the_hourly_data():
    after = datetime(2026, 10, 11, 9, 0, tzinfo=CEST)
    snap = build_snapshot(DAILY, HOURLY, after)
    assert snap.current is None
    assert snap.dew_point is None
    assert snap.hourly == []
    assert snap.daily[0].date == date(2026, 10, 11)


def test_snapshot_with_nothing_downloaded():
    snap = build_snapshot([], [], NOW)
    assert snap.current is None
    assert snap.hourly == []
    assert snap.daily == []


# --- How to react to errors ----------------------------------------------

def test_definitive_auth_error_asks_for_reauth():
    status = KeyStatus()
    decision = status.record_error(IlMeteoAuthError("expired", "x"), ENDPOINT_DAILY, NOW)
    assert decision.action is Action.REAUTH


def test_quota_error_blocks_and_notifies():
    status = KeyStatus()
    for triggered in (True, False):
        err = IlMeteoQuotaExceeded("x", triggered=triggered)
        decision = status.record_error(err, ENDPOINT_HOURLY, NOW)
        assert decision.action is Action.BLOCK
        assert decision.notice is Notice.QUOTA


def test_temporary_errors_retry_silently():
    status = KeyStatus()
    for err in (IlMeteoConnectionError("x"), IlMeteoRequestError("HTTP 400")):
        decision = status.record_error(err, ENDPOINT_DAILY, NOW)
        assert decision.action is Action.RETRY
        assert decision.notice is None


def test_unrecognized_401_is_temporary_for_a_day_then_reauth():
    status = KeyStatus()
    err = IlMeteoUnrecognizedAuthError("Messaggio nuovo")
    first = status.record_error(err, ENDPOINT_DAILY, NOW)
    assert first.action is Action.RETRY
    assert first.notice is Notice.AUTH_UNKNOWN

    almost = NOW + UNRECOGNIZED_AUTH_GRACE - timedelta(minutes=1)
    assert status.record_error(err, ENDPOINT_DAILY, almost).action is Action.RETRY

    expired = NOW + UNRECOGNIZED_AUTH_GRACE
    assert status.record_error(err, ENDPOINT_DAILY, expired).action is Action.REAUTH


def test_grace_period_is_one_day():
    assert timedelta(hours=24) == UNRECOGNIZED_AUTH_GRACE


def test_a_success_resets_the_unrecognized_401_clock():
    status = KeyStatus()
    err = IlMeteoUnrecognizedAuthError("Messaggio nuovo")
    status.record_error(err, ENDPOINT_DAILY, NOW)
    status.record_success()
    later = NOW + UNRECOGNIZED_AUTH_GRACE + timedelta(hours=1)
    # The clock restarts from this new first occurrence.
    assert status.record_error(err, ENDPOINT_DAILY, later).action is Action.RETRY


def test_out_of_scope_endpoint_is_dropped_for_good():
    status = KeyStatus()
    decision = status.record_error(IlMeteoOutOfScope("x"), ENDPOINT_DAILY, NOW)
    assert decision.action is Action.DROP_ENDPOINT
    assert status.endpoints() == [ENDPOINT_HOURLY]


def test_key_covering_no_forecast_endpoint_asks_for_reauth():
    status = KeyStatus()
    status.record_error(IlMeteoOutOfScope("x"), ENDPOINT_DAILY, NOW)
    decision = status.record_error(IlMeteoOutOfScope("x"), ENDPOINT_HOURLY, NOW)
    assert decision.action is Action.REAUTH
    assert status.endpoints() == []


# --- Planning an update --------------------------------------------------

def _tracker(limit=1000):
    return QuotaTracker(limit=limit, rng=random.Random(0))


def test_plan_requests_both_endpoints_normally():
    plan = plan_update(_tracker(), KeyStatus(), NOW)
    assert plan.endpoints == [ENDPOINT_DAILY, ENDPOINT_HOURLY]
    assert plan.notice is None


def test_plan_skips_everything_while_blocked():
    tracker = _tracker()
    tracker.block(NOW)
    plan = plan_update(tracker, KeyStatus(), NOW)
    assert plan.endpoints == []
    assert plan.notice is Notice.QUOTA


def test_plan_blocks_before_crossing_the_local_limit():
    # Not enough budget left for a full update: stop now instead of spending
    # the last request on a half update.
    tracker = _tracker(limit=3)
    for _ in range(2):
        tracker.record_request(NOW)
    plan = plan_update(tracker, KeyStatus(), NOW)
    assert plan.endpoints == []
    assert plan.notice is Notice.QUOTA
    assert tracker.is_blocked(NOW)


def test_plan_skips_dropped_endpoints():
    status = KeyStatus()
    status.record_error(IlMeteoOutOfScope("x"), ENDPOINT_DAILY, NOW)
    plan = plan_update(_tracker(), status, NOW)
    assert plan.endpoints == [ENDPOINT_HOURLY]


# --- Persistence ---------------------------------------------------------

def test_key_status_round_trip():
    status = KeyStatus()
    status.record_error(IlMeteoOutOfScope("x"), ENDPOINT_DAILY, NOW)
    status.record_error(IlMeteoUnrecognizedAuthError("x"), ENDPOINT_HOURLY, NOW)
    data = status.as_dict()
    json.dumps(data)  # plain JSON types only
    restored = KeyStatus.from_dict(data)
    assert restored.endpoints() == [ENDPOINT_HOURLY]
    err = IlMeteoUnrecognizedAuthError("x")
    late = NOW + UNRECOGNIZED_AUTH_GRACE
    assert restored.record_error(err, ENDPOINT_HOURLY, late).action is Action.REAUTH


def test_key_status_from_empty_or_corrupt_data():
    for data in (None, {}, {"out_of_scope": "daily", "unrecognized_since": 3}):
        status = KeyStatus.from_dict(data)
        assert status.endpoints() == [ENDPOINT_DAILY, ENDPOINT_HOURLY]


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    sys.exit(1 if failed else 0)

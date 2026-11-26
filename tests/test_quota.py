"""Unit tests for the per-key daily quota tracker (quota.py).

Run with:  python tests/test_quota.py
No Home Assistant dependency. The rules come from iLMeteo, in writing:
- 1000 requests per day per key, rejected requests included;
- the counter resets at midnight Italian time, and the block lifts a few
  moments after midnight, never before;
- once the limit message arrives, retrying burns quota and unblocks nothing.
"""
import os
import random
import sys
from datetime import UTC, datetime, timedelta, timezone

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "ilmeteo")
)

from quota import (
    DAILY_LIMIT,
    RESUME_DELAY_MAX,
    RESUME_DELAY_MIN,
    QuotaTracker,
)

CEST = timezone(timedelta(hours=2))  # Italian summer time
CET = timezone(timedelta(hours=1))  # Italian winter time


def _tracker(seed=0, limit=DAILY_LIMIT):
    return QuotaTracker(limit=limit, rng=random.Random(seed))


# --- Counting ------------------------------------------------------------

def test_limit_is_the_documented_one():
    assert DAILY_LIMIT == 1000


def test_counts_requests_within_the_italian_day():
    t = _tracker()
    now = datetime(2026, 10, 8, 10, 0, tzinfo=CEST)
    for _ in range(5):
        t.record_request(now)
    assert t.used(now) == 5
    assert t.used(now.replace(hour=23, minute=59)) == 5


def test_counter_resets_at_italian_midnight_not_utc():
    t = _tracker()
    t.record_request(datetime(2026, 10, 8, 21, 0, tzinfo=CEST))
    # 21:30 UTC on the 8th is 23:30 in Italy: same day, still counted.
    assert t.used(datetime(2026, 10, 8, 21, 30, tzinfo=UTC)) == 1
    # 23:30 UTC on the 8th is already 01:30 on the 9th in Italy.
    assert t.used(datetime(2026, 10, 8, 23, 30, tzinfo=UTC)) == 0


def test_can_request_stops_at_the_limit():
    t = _tracker(limit=3)
    now = datetime(2026, 10, 8, 10, 0, tzinfo=CEST)
    assert t.can_request(now)
    t.record_request(now)
    t.record_request(now)
    assert t.can_request(now)
    assert not t.can_request(now, count=2)  # an update needs two calls
    t.record_request(now)
    assert not t.can_request(now)


def test_naive_datetimes_are_rejected():
    t = _tracker()
    naive = datetime(2026, 10, 8, 10, 0)
    for call in (t.record_request, t.used, t.can_request, t.block, t.is_blocked):
        try:
            call(naive)
        except ValueError:
            continue
        raise AssertionError(f"{call.__name__} accepted a naive datetime")


# --- Blocking ------------------------------------------------------------

def test_block_lasts_until_after_next_italian_midnight():
    t = _tracker()
    now = datetime(2026, 10, 8, 18, 0, tzinfo=CEST)
    resume = t.block(now)
    midnight = datetime(2026, 10, 9, 0, 0, tzinfo=CEST)
    assert midnight + RESUME_DELAY_MIN <= resume <= midnight + RESUME_DELAY_MAX
    assert t.blocked_until == resume
    assert t.is_blocked(now)
    assert t.is_blocked(midnight)  # never before midnight, nor exactly at it
    assert not t.can_request(now)
    assert not t.is_blocked(resume)
    assert t.can_request(resume)


def test_block_just_before_midnight_still_waits_for_midnight():
    t = _tracker()
    resume = t.block(datetime(2026, 10, 8, 23, 59, 30, tzinfo=CEST))
    assert resume >= datetime(2026, 10, 9, 0, 0, tzinfo=CEST) + RESUME_DELAY_MIN


def test_repeated_block_does_not_move_the_resume_time():
    # Every request sent to a blocked key gets "Accesso temporaneamente
    # bloccato": those must not keep pushing the resume time around.
    t = _tracker()
    first = t.block(datetime(2026, 10, 8, 18, 0, tzinfo=CEST))
    again = t.block(datetime(2026, 10, 8, 18, 30, tzinfo=CEST))
    assert again == first


def test_new_day_after_resume_starts_from_zero():
    t = _tracker(limit=2)
    day = datetime(2026, 10, 8, 18, 0, tzinfo=CEST)
    t.record_request(day)
    t.record_request(day)
    resume = t.block(day)
    assert t.used(resume) == 0
    assert t.can_request(resume, count=2)


def test_resume_delay_differs_between_installations():
    # The random delay spreads installations so they do not all hit the
    # gateway at 00:00:00. Different seeds stand in for different installs.
    now = datetime(2026, 10, 8, 18, 0, tzinfo=CEST)
    resumes = {_tracker(seed).block(now) for seed in range(20)}
    assert len(resumes) > 10


def test_delay_bounds_are_a_few_minutes():
    assert timedelta(0) < RESUME_DELAY_MIN < RESUME_DELAY_MAX <= timedelta(minutes=15)


# --- Daylight saving time ------------------------------------------------

def test_block_on_the_night_summer_time_ends():
    # 25 Oct 2026: clocks go back at 03:00 CEST. Midnight is still CEST.
    t = _tracker()
    resume = t.block(datetime(2026, 10, 24, 22, 0, tzinfo=CEST))
    midnight = datetime(2026, 10, 25, 0, 0, tzinfo=CEST)
    assert midnight + RESUME_DELAY_MIN <= resume <= midnight + RESUME_DELAY_MAX


def test_block_on_the_first_winter_day():
    t = _tracker()
    resume = t.block(datetime(2026, 10, 25, 12, 0, tzinfo=CET))
    midnight = datetime(2026, 10, 26, 0, 0, tzinfo=CET)  # 23:00 UTC on the 25th
    assert midnight + RESUME_DELAY_MIN <= resume <= midnight + RESUME_DELAY_MAX


# --- Persistence ---------------------------------------------------------

def test_state_round_trip():
    # A restart while blocked must not lose the block: retrying would only
    # burn quota on a key the gateway is already refusing.
    t = _tracker(limit=10)
    now = datetime(2026, 10, 8, 18, 0, tzinfo=CEST)
    for _ in range(4):
        t.record_request(now)
    resume = t.block(now)
    restored = QuotaTracker.from_dict(t.as_dict(), limit=10, rng=random.Random(1))
    assert restored.used(now) == 4
    assert restored.blocked_until == resume
    assert restored.is_blocked(now)


def test_state_from_a_previous_day_starts_fresh():
    t = _tracker()
    yesterday = datetime(2026, 10, 7, 20, 0, tzinfo=CEST)
    t.record_request(yesterday)
    restored = QuotaTracker.from_dict(t.as_dict(), rng=random.Random(1))
    today = datetime(2026, 10, 8, 9, 0, tzinfo=CEST)
    assert restored.used(today) == 0
    assert restored.can_request(today)


def test_state_is_plain_json_types():
    import json

    t = _tracker()
    now = datetime(2026, 10, 8, 18, 0, tzinfo=CEST)
    t.record_request(now)
    t.block(now)
    json.dumps(t.as_dict())  # must not raise


def test_empty_or_corrupt_state_starts_fresh():
    now = datetime(2026, 10, 8, 18, 0, tzinfo=CEST)
    for data in (None, {}, {"day": "not a date", "count": "x", "blocked_until": 5}):
        t = QuotaTracker.from_dict(data, rng=random.Random(1))
        assert t.used(now) == 0
        assert not t.is_blocked(now)


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

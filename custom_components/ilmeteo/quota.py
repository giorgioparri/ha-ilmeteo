"""Per-key daily quota tracking for the iLMeteo API Gateway.

No Home Assistant dependency. One QuotaTracker per API key, shared by every
config entry that uses that key: the gateway counts requests per key, not
per location.

Rules, as stated in writing by iLMeteo:
- DAILY_LIMIT requests per key per day; rejected requests count too, including
  those sent to a key that is already blocked;
- the counter resets at midnight Italian time, and the block lifts a few
  moments after midnight, never before.

Hence: stop entirely at the first limit message, and resume only after the
next Italian midnight plus a random delay, so installations do not all hit
the gateway in the same second.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

DAILY_LIMIT = 1000
QUOTA_TIMEZONE = ZoneInfo("Europe/Rome")
RESUME_DELAY_MIN = timedelta(minutes=1)
RESUME_DELAY_MAX = timedelta(minutes=10)


def _check_aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("QuotaTracker needs timezone-aware datetimes")


def _italian_day(now: datetime) -> date:
    return now.astimezone(QUOTA_TIMEZONE).date()


def _next_italian_midnight(now: datetime) -> datetime:
    tomorrow = _italian_day(now) + timedelta(days=1)
    return datetime.combine(tomorrow, time.min, tzinfo=QUOTA_TIMEZONE)


class QuotaTracker:
    """Count requests per Italian day and hold a block until after midnight."""

    def __init__(
        self,
        *,
        limit: int = DAILY_LIMIT,
        rng: random.Random | None = None,
    ) -> None:
        self._limit = limit
        self._rng = rng or random.Random()
        self._day: date | None = None
        self._count = 0
        self._blocked_until: datetime | None = None

    @property
    def blocked_until(self) -> datetime | None:
        """When requests may resume, or None if not blocked."""
        return self._blocked_until

    def _roll(self, now: datetime) -> None:
        _check_aware(now)
        today = _italian_day(now)
        if self._day != today:
            self._day = today
            self._count = 0

    def used(self, now: datetime) -> int:
        """Requests counted so far in the Italian day containing now."""
        self._roll(now)
        return self._count

    def record_request(self, now: datetime) -> None:
        """Count one request sent at now, whatever its outcome."""
        self._roll(now)
        self._count += 1

    def is_blocked(self, now: datetime) -> bool:
        """True while a block is in force at now."""
        _check_aware(now)
        if self._blocked_until is None:
            return False
        if now >= self._blocked_until:
            self._blocked_until = None
            return False
        return True

    def can_request(self, now: datetime, count: int = 1) -> bool:
        """True if count more requests fit in today's budget and no block holds."""
        if self.is_blocked(now):
            return False
        return self.used(now) + count <= self._limit

    def block(self, now: datetime) -> datetime:
        """Block until after the next Italian midnight; return the resume time.

        A block already in force is kept as is: the follow-up 'access blocked'
        answers must not move the resume time.
        """
        if self.is_blocked(now):
            return self._blocked_until  # type: ignore[return-value]
        delay_s = self._rng.uniform(
            RESUME_DELAY_MIN.total_seconds(), RESUME_DELAY_MAX.total_seconds()
        )
        self._blocked_until = _next_italian_midnight(now) + timedelta(seconds=delay_s)
        return self._blocked_until

    def as_dict(self) -> dict[str, Any]:
        """State as JSON-safe types, for HA's Store."""
        return {
            "day": self._day.isoformat() if self._day else None,
            "count": self._count,
            "blocked_until": (
                self._blocked_until.isoformat() if self._blocked_until else None
            ),
        }

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any] | None,
        *,
        limit: int = DAILY_LIMIT,
        rng: random.Random | None = None,
    ) -> QuotaTracker:
        """Rebuild a tracker from as_dict(); anything unreadable starts fresh."""
        tracker = cls(limit=limit, rng=rng)
        if not isinstance(data, dict):
            return tracker
        try:
            day = date.fromisoformat(data["day"])
            count = int(data["count"])
        except (KeyError, TypeError, ValueError):
            day, count = None, 0
        tracker._day, tracker._count = day, count
        try:
            until = datetime.fromisoformat(data["blocked_until"])
            tracker._blocked_until = until if until.tzinfo else None
        except (KeyError, TypeError, ValueError):
            tracker._blocked_until = None
        return tracker

"""Pure update logic for the iLMeteo coordinator.

No Home Assistant dependency. The coordinator wires these pieces to HA
(scheduling, storage, persistent notifications, reauth); every decision is
taken here so it can be tested without HA:

- request_window: which dates to ask the gateway for;
- build_snapshot: what the entities show at a given instant, computed from
  the last downloaded lists, so the current slot keeps advancing hour by hour
  even when no request can be sent;
- KeyStatus: per-key memory of endpoints out of scope and of unrecognized
  401s, and the action each gateway error calls for;
- plan_update: which endpoints to call now, given quota and scope.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any

from .client import (
    DailyForecast,
    HourlyForecast,
    IlMeteoAuthError,
    IlMeteoError,
    IlMeteoOutOfScope,
    IlMeteoQuotaExceeded,
    IlMeteoUnrecognizedAuthError,
    current_slot,
)
from .quota import QUOTA_TIMEZONE, QuotaTracker

ENDPOINT_DAILY = "daily"
ENDPOINT_HOURLY = "hourly"
ALL_ENDPOINTS = (ENDPOINT_DAILY, ENDPOINT_HOURLY)

# Hourly data is requested for today and the next two days (71 slots).
HOURLY_EXTRA_DAYS = 2

# A 401 with an unknown message is treated as temporary; if no request
# succeeds for this long, the key is considered bad and reauth is asked.
UNRECOGNIZED_AUTH_GRACE = timedelta(hours=24)


# --- What to request -------------------------------------------------------

def request_window(now: datetime) -> tuple[date, date]:
    """Return (first, last) Italian date of the forecast to request."""
    today = now.astimezone(QUOTA_TIMEZONE).date()
    return today, today + timedelta(days=HOURLY_EXTRA_DAYS)


# --- What to show ----------------------------------------------------------

def dew_point(temperature: float | None, humidity: float | None) -> float | None:
    """Dew point in °C from temperature (°C) and relative humidity (%).

    Magnus formula with the Sonntag (1990) constants, accurate to about
    0.1 °C between -45 and 60 °C.
    """
    if temperature is None or humidity is None or humidity <= 0:
        return None
    a, b = 17.62, 243.12
    gamma = math.log(humidity / 100.0) + a * temperature / (b + temperature)
    return b * gamma / (a - gamma)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """What the entities show at one instant."""

    current: HourlyForecast | None
    dew_point: float | None
    hourly: list[HourlyForecast]
    daily: list[DailyForecast]


def build_snapshot(
    daily: list[DailyForecast],
    hourly: list[HourlyForecast],
    now: datetime,
) -> Snapshot:
    """Project downloaded lists onto now: drop the past, pick the current slot."""
    current = current_slot(hourly, now)
    today = now.astimezone(QUOTA_TIMEZONE).date()
    return Snapshot(
        current=current,
        dew_point=(
            dew_point(current.temperature, current.humidity) if current else None
        ),
        hourly=[s for s in hourly if s.time + timedelta(hours=1) > now],
        daily=[d for d in daily if d.date >= today],
    )


# --- How to react to errors ------------------------------------------------

class Action(StrEnum):
    """What the coordinator must do after a failed request."""

    RETRY = "retry"  # temporary: keep the cache, try again next cycle
    BLOCK = "block"  # quota: stop every request until after midnight
    DROP_ENDPOINT = "drop_endpoint"  # out of scope: never call it again
    REAUTH = "reauth"  # the key is unusable: ask the user for a new one


class Notice(StrEnum):
    """Persistent notification to show while serving cached data."""

    QUOTA = "quota"
    AUTH_UNKNOWN = "auth_unknown"


@dataclass(frozen=True, slots=True)
class Decision:
    """Outcome of KeyStatus.record_error()."""

    action: Action
    notice: Notice | None = None


@dataclass
class KeyStatus:
    """Per-key memory shared by every location using the same API key."""

    out_of_scope: set[str] = field(default_factory=set)
    unrecognized_since: datetime | None = None

    def endpoints(self) -> list[str]:
        """Forecast endpoints this key may still be asked for, in call order."""
        return [e for e in ALL_ENDPOINTS if e not in self.out_of_scope]

    def record_success(self) -> None:
        """A request went through: an unknown 401 was not about the key."""
        self.unrecognized_since = None

    def record_error(
        self, err: IlMeteoError, endpoint: str, now: datetime
    ) -> Decision:
        """Remember what the error says about the key and pick the action."""
        if isinstance(err, IlMeteoAuthError):
            return Decision(Action.REAUTH)
        if isinstance(err, IlMeteoQuotaExceeded):
            return Decision(Action.BLOCK, Notice.QUOTA)
        if isinstance(err, IlMeteoOutOfScope):
            self.out_of_scope.add(endpoint)
            if not self.endpoints():
                return Decision(Action.REAUTH)
            return Decision(Action.DROP_ENDPOINT)
        if isinstance(err, IlMeteoUnrecognizedAuthError):
            if self.unrecognized_since is None:
                self.unrecognized_since = now
            if now - self.unrecognized_since >= UNRECOGNIZED_AUTH_GRACE:
                return Decision(Action.REAUTH)
            return Decision(Action.RETRY, Notice.AUTH_UNKNOWN)
        return Decision(Action.RETRY)

    def as_dict(self) -> dict[str, Any]:
        """State as JSON-safe types, for HA's Store."""
        return {
            "out_of_scope": sorted(self.out_of_scope),
            "unrecognized_since": (
                self.unrecognized_since.isoformat()
                if self.unrecognized_since
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> KeyStatus:
        """Rebuild from as_dict(); anything unreadable starts fresh."""
        status = cls()
        if not isinstance(data, dict):
            return status
        scope = data.get("out_of_scope")
        if isinstance(scope, list):
            status.out_of_scope = {e for e in scope if e in ALL_ENDPOINTS}
        try:
            since = datetime.fromisoformat(data["unrecognized_since"])
            status.unrecognized_since = since if since.tzinfo else None
        except (KeyError, TypeError, ValueError):
            status.unrecognized_since = None
        return status


# --- Planning an update ----------------------------------------------------

@dataclass(frozen=True, slots=True)
class Plan:
    """Endpoints to call now; empty means serve the cache."""

    endpoints: list[str]
    notice: Notice | None = None


def plan_update(tracker: QuotaTracker, status: KeyStatus, now: datetime) -> Plan:
    """Decide which endpoints to call now.

    If today's budget cannot fit a full update, block now: a half update
    would spend the last requests without refreshing everything.
    """
    endpoints = status.endpoints()
    if tracker.is_blocked(now):
        return Plan([], Notice.QUOTA)
    if not tracker.can_request(now, count=len(endpoints)):
        tracker.block(now)
        return Plan([], Notice.QUOTA)
    return Plan(endpoints)

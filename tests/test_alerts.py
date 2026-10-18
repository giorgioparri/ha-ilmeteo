"""Unit tests for alert providers (alerts.py).

Run with:  python tests/test_alerts.py
No Home Assistant dependency: HeuristicAlertProvider is pure, and the DPC
providers only need hass.states.get(), stubbed here with a minimal fake.

The heuristic provider reads the coordinator's Snapshot (update.py). Each
scenario builds only the fields it needs; every other field stays None, as
when the gateway leaves it out.
"""
import asyncio
import dataclasses
import os
import sys
import types
from datetime import date, datetime, timedelta, timezone

# alerts.py imports its siblings relatively, as modules inside an HA
# integration must: register the folder as a bare "ilmeteo" package so those
# imports resolve without running __init__.py, which needs Home Assistant.
_PKG_DIR = os.path.join(os.path.dirname(__file__), "..", "custom_components", "ilmeteo")
_pkg = types.ModuleType("ilmeteo")
_pkg.__path__ = [_PKG_DIR]
sys.modules.setdefault("ilmeteo", _pkg)

from ilmeteo.alerts import (  # noqa: E402
    DpcSensorAlertProvider,
    DpcVigilanceProvider,
    HeuristicAlertProvider,
    WeatherAlert,
)
from ilmeteo.client import DailyForecast, HourlyForecast  # noqa: E402
from ilmeteo.update import Snapshot  # noqa: E402

CEST = timezone(timedelta(hours=2))
TODAY = date(2026, 10, 8)
KMH = 3.6  # m/s -> km/h


def _run(coro):
    return asyncio.run(coro)


def _ids(alerts):
    return {a.alert_id for a in alerts}


# --- Snapshot builders ---------------------------------------------------

def _day(offset=0, **values):
    """A DailyForecast for TODAY + offset with only the given fields set."""
    fields = {f.name: None for f in dataclasses.fields(DailyForecast)}
    fields.update(date=TODAY + timedelta(days=offset), **values)
    return DailyForecast(**fields)


def _slot(hour, offset=0, **values):
    """An HourlyForecast at hour:00 of TODAY + offset (Italian time)."""
    fields = {f.name: None for f in dataclasses.fields(HourlyForecast)}
    day = TODAY + timedelta(days=offset)
    fields.update(
        time=datetime(day.year, day.month, day.day, hour, tzinfo=CEST),
        is_night=False,
        **values,
    )
    return HourlyForecast(**fields)


def _snapshot(daily=(), hourly=(), current=None):
    return Snapshot(current=current, dew_point=None, hourly=list(hourly), daily=list(daily))


def _heuristic(snapshot, active=None):
    return _run(HeuristicAlertProvider().async_get_alerts(
        snapshot, "5658", "Rapolano Terme", active_alert_ids=active,
    ))


# --- HeuristicAlertProvider: temperatures and rain -----------------------

def test_no_alerts_on_empty_data():
    assert _heuristic(_snapshot()) == []
    assert _heuristic(None) == []


def test_heat_thresholds_today():
    alerts = _heuristic(_snapshot(daily=[_day(0, temperature_max=39), _day(1)]))
    heat = [a for a in alerts if a.alert_id == "heuristic_heat_today"]
    assert len(heat) == 1
    assert heat[0].severity == "orange"


def test_heat_below_threshold_no_alert():
    alerts = _heuristic(_snapshot(daily=[_day(0, temperature_max=30)]))
    assert not any(a.kind == "heat" for a in alerts)


def test_today_and_tomorrow_are_independent_alerts():
    snap = _snapshot(daily=[
        _day(0, temperature_max=39),
        _day(1, temperature_max=20, temperature_min=-6),
    ])
    ids = _ids(_heuristic(snap))
    assert "heuristic_heat_today" in ids
    assert "heuristic_heat_tomorrow" not in ids
    assert "heuristic_cold_tomorrow" in ids
    assert "heuristic_cold_today" not in ids


def test_days_are_matched_by_date_not_by_position():
    # Today's row missing (e.g. just after midnight on stale data): the only
    # row is tomorrow's and must not be read as today's.
    snap = _snapshot(daily=[_day(1, temperature_max=39)], current=_slot(10))
    ids = _ids(_heuristic(snap))
    assert "heuristic_heat_tomorrow" in ids
    assert "heuristic_heat_today" not in ids


def test_rain_probability_threshold():
    alerts = _heuristic(_snapshot(daily=[_day(0, precipitation_probability=85)]))
    assert "heuristic_rain_today" in _ids(alerts)


def test_alerts_carry_day_field():
    snap = _snapshot(daily=[_day(0, temperature_max=39), _day(1, temperature_max=39)])
    days = {a.alert_id: a.day for a in _heuristic(snap)}
    assert days["heuristic_heat_today"] == "today"
    assert days["heuristic_heat_tomorrow"] == "tomorrow"


# --- HeuristicAlertProvider: wind (m/s in, km/h thresholds and text) -----

def test_wind_is_converted_to_kmh():
    # 12 m/s = 43.2 km/h: above the 40 km/h yellow threshold.
    alerts = _heuristic(_snapshot(daily=[_day(0, wind_speed=12)]))
    wind = next(a for a in alerts if a.alert_id == "heuristic_wind_today")
    assert wind.severity == "yellow"
    assert "43 km/h" in wind.message


def test_wind_below_threshold_in_ms_stays_quiet():
    # 10 m/s = 36 km/h: would wrongly alert if m/s were compared to km/h.
    assert _heuristic(_snapshot(daily=[_day(0, wind_speed=10)])) == []


def test_current_wind_only_applies_to_today():
    # No wind in either daily row: today falls back to the current slot,
    # tomorrow must not.
    snap = _snapshot(daily=[_day(0), _day(1)], current=_slot(10, wind_speed=70 / KMH))
    ids = _ids(_heuristic(snap))
    assert "heuristic_wind_today" in ids
    assert "heuristic_wind_tomorrow" not in ids


# --- HeuristicAlertProvider: storms and hail from outlook codes ----------

def test_hail_detected_from_outlook_code():
    for code in (17, 19, 20):
        snap = _snapshot(daily=[_day(0)], hourly=[_slot(15, outlook=code)])
        assert "heuristic_hail_today" in _ids(_heuristic(snap)), code


def test_storm_with_hail_raises_both_alerts():
    # "temporale con grandine": the 1.x text match fired both, so does this.
    snap = _snapshot(daily=[_day(0)], hourly=[_slot(15, outlook=20)])
    ids = _ids(_heuristic(snap))
    assert {"heuristic_hail_today", "heuristic_storm_today"} <= ids


def test_storm_severity_escalation():
    mild = _snapshot(daily=[_day(0)], hourly=[
        _slot(15, outlook=13, precipitation_intensity="COPIOUS"),
    ])
    strong = _snapshot(daily=[_day(0)], hourly=[
        _slot(15, outlook=13, precipitation_intensity="STRONG"),
    ])
    mild_storm = next(a for a in _heuristic(mild) if a.alert_id == "heuristic_storm_today")
    strong_storm = next(a for a in _heuristic(strong) if a.alert_id == "heuristic_storm_today")
    assert mild_storm.severity == "yellow"
    assert strong_storm.severity == "orange"


def test_storm_in_current_slot_counts_for_today():
    snap = _snapshot(daily=[_day(0)], current=_slot(10, outlook=16))
    assert "heuristic_storm_today" in _ids(_heuristic(snap))


def test_slots_count_for_their_own_day():
    snap = _snapshot(daily=[_day(0), _day(1)], hourly=[_slot(14, offset=1, outlook=13)])
    ids = _ids(_heuristic(snap))
    assert "heuristic_storm_tomorrow" in ids
    assert "heuristic_storm_today" not in ids


def test_slots_after_tomorrow_are_ignored():
    snap = _snapshot(daily=[_day(0)], hourly=[_slot(14, offset=2, outlook=17)])
    assert _heuristic(snap) == []


def test_rain_alone_is_not_a_storm():
    snap = _snapshot(daily=[_day(0)], hourly=[
        _slot(6, outlook=10, precipitation_intensity="REALLY_STRONG"),
    ])
    assert _heuristic(snap) == []


# --- HeuristicAlertProvider: hysteresis ----------------------------------

def test_hysteresis_keeps_heat_alert_alive():
    # 34 °C is below HEAT_YELLOW_C (35) but the alert was active: kept alive.
    snap = _snapshot(daily=[_day(0, temperature_max=34)])
    alerts = _heuristic(snap, active=frozenset(["heuristic_heat_today"]))
    assert any(a.alert_id == "heuristic_heat_today" for a in alerts)


def test_hysteresis_clears_alert_below_delta():
    # 32 °C is below HEAT_YELLOW_C - HEAT_HYSTERESIS_C (33): cleared.
    snap = _snapshot(daily=[_day(0, temperature_max=32)])
    alerts = _heuristic(snap, active=frozenset(["heuristic_heat_today"]))
    assert not any(a.alert_id == "heuristic_heat_today" for a in alerts)


def test_no_hysteresis_without_active_alert():
    snap = _snapshot(daily=[_day(0, temperature_max=34)])
    assert not any(a.alert_id == "heuristic_heat_today" for a in _heuristic(snap))


def test_signature_changes_with_severity():
    a = WeatherAlert("x", "yellow", "heat", "t", "m", "heuristic")
    b = WeatherAlert("x", "orange", "heat", "t", "m", "heuristic")
    assert a.signature != b.signature


# --- DpcSensorAlertProvider ----------------------------------------------

class _FakeState:
    def __init__(self, state, attributes):
        self.state = state
        self.attributes = attributes


class _FakeStates:
    def __init__(self, state):
        self._state = state

    def get(self, entity_id):
        return self._state


class _FakeHass:
    def __init__(self, state):
        self.states = _FakeStates(state)


def test_dpc_missing_entity_returns_no_alerts():
    hass = _FakeHass(None)
    provider = DpcSensorAlertProvider(hass, "sensor.dpc_alert")
    alerts = _run(provider.async_get_alerts(_snapshot(), "1", "Roma"))
    assert alerts == []


def test_dpc_unavailable_state_returns_no_alerts():
    hass = _FakeHass(_FakeState("unavailable", {}))
    provider = DpcSensorAlertProvider(hass, "sensor.dpc_alert")
    alerts = _run(provider.async_get_alerts(_snapshot(), "1", "Roma"))
    assert alerts == []


def test_dpc_events_today_and_tomorrow():
    state = _FakeState("2", {
        "events_today": [
            {"risk": "Temporali", "alert": "Allerta arancione", "level": 3, "info": "info"},
        ],
        "events_tomorrow": [
            {"risk": "Idrogeologico", "alert": "Allerta gialla", "level": 2, "info": "info2"},
        ],
    })
    hass = _FakeHass(state)
    provider = DpcSensorAlertProvider(hass, "sensor.dpc_alert")
    alerts = _run(provider.async_get_alerts(_snapshot(), "1", "Roma"))
    ids = _ids(alerts)
    assert "dpc_temporali_events_today" in ids
    assert "dpc_idrogeologico_events_tomorrow" in ids
    today = next(a for a in alerts if a.alert_id == "dpc_temporali_events_today")
    assert today.severity == "orange"
    assert today.source == "protezione_civile"


def test_dpc_ignores_level_below_2():
    state = _FakeState("1", {
        "events_today": [{"risk": "Temporali", "alert": "Verde", "level": 1, "info": ""}],
    })
    hass = _FakeHass(state)
    provider = DpcSensorAlertProvider(hass, "sensor.dpc_alert")
    alerts = _run(provider.async_get_alerts(_snapshot(), "1", "Roma"))
    assert alerts == []


def test_dpc_falls_back_to_aggregate_today_tomorrow():
    # Older component versions: no events_today/events_tomorrow attributes.
    state = _FakeState("3", {"today": {"alert": "Allerta arancione", "level": 3, "info": "x"}})
    hass = _FakeHass(state)
    provider = DpcSensorAlertProvider(hass, "sensor.dpc_alert")
    alerts = _run(provider.async_get_alerts(_snapshot(), "1", "Roma"))
    assert _ids(alerts) == {"dpc_today"}


def test_dpc_vigilance_day_field():
    state = _FakeState("2", {
        "aftertomorrow": {
            "level": 2,
            "precipitation": "Diffuse",
            "phenomena": [
                {"event": "Venti", "value": "burrasca", "distance": 10, "direction": "NW"},
            ],
        },
    })
    hass = _FakeHass(state)
    provider = DpcVigilanceProvider(hass, "sensor.dpc_vigilance")
    alerts = _run(provider.async_get_alerts(_snapshot(), "1", "Roma"))
    assert all(a.day == "aftertomorrow" for a in alerts)
    assert len(alerts) == 2  # day-level + 1 phenomenon


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

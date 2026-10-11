"""Weather alert model and provider abstraction.

The iLMeteo API Gateway has no alert endpoint. Until iLMeteo provides one,
alerts are derived by HeuristicAlertProvider from the forecast already in the
coordinator (update.Snapshot), alongside the official Protezione Civile
bulletins read from the DPC integration's sensors.

AlertProvider is deliberately generic so a future provider backed by
Protezione Civile open data (bollettino di criticità per zona di allerta) or
by an official iLMeteo feed can be added without touching alert_manager.py.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from .const import POURING_INTENSITIES
from .quota import QUOTA_TIMEZONE

if TYPE_CHECKING:
    from .client import DailyForecast, HourlyForecast
    from .update import Snapshot

# Heuristic thresholds. These are our own invention, not official
# Protezione Civile / iLMeteo thresholds — tune here if needed.
HEAT_YELLOW_C = 35
HEAT_ORANGE_C = 38
COLD_YELLOW_C = 0
COLD_ORANGE_C = -5
WIND_YELLOW_KMH = 40
WIND_ORANGE_KMH = 60
RAIN_PROB_YELLOW = 80

# Hysteresis deltas: an active alert is kept alive until the value drops
# this much below the threshold that triggered it. Prevents rapid on/off
# oscillation when values hover near a boundary between refreshes.
HEAT_HYSTERESIS_C = 2
COLD_HYSTERESIS_C = 2
WIND_HYSTERESIS_KMH = 5
RAIN_PROB_HYSTERESIS = 5

# Gateway outlook codes (glossary) standing for storms and for hail. 19 and
# 20 ("temporale con grandine") are both, as the 1.x label match was.
STORM_OUTLOOKS = frozenset({13, 16, 19, 20})
HAIL_OUTLOOKS = frozenset({17, 19, 20})

MS_TO_KMH = 3.6


@dataclass
class WeatherAlert:
    """A single active weather alert for a location."""

    alert_id: str  # stable key per condition type, e.g. "heuristic_heat"
    severity: str  # "yellow" | "orange" | "red"
    kind: str  # "heat" | "cold" | "wind" | "storm" | "hail" | "rain"
    title: str
    message: str
    source: str  # provider name, e.g. "heuristic"
    day: str = "today"  # "today" | "tomorrow" | "aftertomorrow" — grouping key for batched notifications

    @property
    def signature(self) -> str:
        """Changes whenever the alert is newly issued or its severity changes."""
        return f"{self.alert_id}:{self.severity}"


class AlertProvider(ABC):
    """Base class for anything that can produce WeatherAlert objects."""

    name: str = "base"

    @abstractmethod
    async def async_get_alerts(
        self,
        coordinator_data: Snapshot | None,
        citta: str,
        place_name: str,
        active_alert_ids: frozenset[str] | None = None,
    ) -> list[WeatherAlert]:
        """Return the currently active alerts for this location.

        active_alert_ids: the set of alert_ids currently in the dedup store.
        Providers that implement hysteresis use this to keep an alert alive
        even when the value has dipped just below the trigger threshold.
        """


class HeuristicAlertProvider(AlertProvider):
    """Derives alerts from the forecast snapshot already in the coordinator.

    Evaluates today and tomorrow independently: each produces its own
    alert_id (e.g. heuristic_heat_today vs heuristic_heat_tomorrow), so they
    dedup and notify separately. Days are matched by Italian date, never by
    list position. The current slot only applies to today.

    Hysteresis: once an alert is active, it is kept alive until the value
    drops below (threshold - delta), preventing rapid on/off oscillation
    when values hover near a boundary between 30-minute refreshes.

    Not an official alert source — see module docstring.
    """

    name = "heuristic"

    async def async_get_alerts(
        self,
        coordinator_data: Snapshot | None,
        citta: str,
        place_name: str,
        active_alert_ids: frozenset[str] | None = None,
    ) -> list[WeatherAlert]:
        snapshot = coordinator_data
        if snapshot is None:
            return []
        today = self._today(snapshot)
        if today is None:
            return []
        active = active_alert_ids or frozenset()

        alerts: list[WeatherAlert] = []
        for offset, suffix, label in ((0, "today", "oggi"), (1, "tomorrow", "domani")):
            day = today + timedelta(days=offset)
            summary = next((d for d in snapshot.daily if d.date == day), None)
            slots = [s for s in snapshot.hourly if self._date(s) == day]
            current = snapshot.current if offset == 0 else None
            alerts += self._heat_cold(summary, suffix, label, active)
            alerts += self._wind(summary, current, suffix, label, active)
            alerts += self._storm_hail(slots, current, suffix, label)
            alerts += self._rain(summary, suffix, label, active)
        return alerts

    @staticmethod
    def _date(slot: HourlyForecast) -> date:
        return slot.time.astimezone(QUOTA_TIMEZONE).date()

    @classmethod
    def _today(cls, snapshot: Snapshot) -> date | None:
        """Italian date the snapshot refers to.

        The current slot is the most direct witness; otherwise build_snapshot
        guarantees the first hourly slot is the current hour and the first
        daily row is today or later, so the earliest of the two is used.
        """
        if snapshot.current is not None:
            return cls._date(snapshot.current)
        candidates = [d.date for d in snapshot.daily[:1]]
        candidates += [cls._date(s) for s in snapshot.hourly[:1]]
        return min(candidates) if candidates else None

    @staticmethod
    def _heat_cold(
        summary: DailyForecast | None, suffix: str, label: str, active: frozenset[str]
    ) -> list[WeatherAlert]:
        alerts: list[WeatherAlert] = []
        tmax = summary.temperature_max if summary else None
        tmin = summary.temperature_min if summary else None
        h = HEAT_HYSTERESIS_C
        c = COLD_HYSTERESIS_C

        heat_id = f"heuristic_heat_{suffix}"
        cold_id = f"heuristic_cold_{suffix}"
        heat_active = heat_id in active
        cold_active = cold_id in active

        if tmax is not None:
            if tmax >= HEAT_ORANGE_C or (heat_active and tmax >= HEAT_ORANGE_C - h):
                alerts.append(WeatherAlert(
                    heat_id, "orange", "heat", f"Caldo estremo ({label})",
                    f"Temperatura massima prevista {label}: {tmax:.0f}°C.", "heuristic", day=suffix,
                ))
            elif tmax >= HEAT_YELLOW_C or (heat_active and tmax >= HEAT_YELLOW_C - h):
                alerts.append(WeatherAlert(
                    heat_id, "yellow", "heat", f"Caldo intenso ({label})",
                    f"Temperatura massima prevista {label}: {tmax:.0f}°C.", "heuristic", day=suffix,
                ))

        if tmin is not None:
            if tmin <= COLD_ORANGE_C or (cold_active and tmin <= COLD_ORANGE_C + c):
                alerts.append(WeatherAlert(
                    cold_id, "orange", "cold", f"Gelo intenso ({label})",
                    f"Temperatura minima prevista {label}: {tmin:.0f}°C.", "heuristic", day=suffix,
                ))
            elif tmin <= COLD_YELLOW_C or (cold_active and tmin <= COLD_YELLOW_C + c):
                alerts.append(WeatherAlert(
                    cold_id, "yellow", "cold", f"Gelo ({label})",
                    f"Temperatura minima prevista {label}: {tmin:.0f}°C.", "heuristic", day=suffix,
                ))

        return alerts

    @staticmethod
    def _wind(
        summary: DailyForecast | None, current: HourlyForecast | None,
        suffix: str, label: str, active: frozenset[str]
    ) -> list[WeatherAlert]:
        speed_ms = summary.wind_speed if summary else None
        if speed_ms is None and current is not None:
            speed_ms = current.wind_speed
        if speed_ms is None:
            return []
        speed = speed_ms * MS_TO_KMH  # thresholds and messages stay in km/h

        wind_id = f"heuristic_wind_{suffix}"
        wind_active = wind_id in active
        h = WIND_HYSTERESIS_KMH

        if speed >= WIND_ORANGE_KMH or (wind_active and speed >= WIND_ORANGE_KMH - h):
            return [WeatherAlert(
                wind_id, "orange", "wind", f"Vento forte ({label})",
                f"Velocità del vento prevista {label}: {speed:.0f} km/h.", "heuristic", day=suffix,
            )]
        if speed >= WIND_YELLOW_KMH or (wind_active and speed >= WIND_YELLOW_KMH - h):
            return [WeatherAlert(
                wind_id, "yellow", "wind", f"Vento sostenuto ({label})",
                f"Velocità del vento prevista {label}: {speed:.0f} km/h.", "heuristic", day=suffix,
            )]
        return []

    @staticmethod
    def _storm_hail(
        slots: list[HourlyForecast], current: HourlyForecast | None,
        suffix: str, label: str
    ) -> list[WeatherAlert]:
        considered = [*slots, current] if current is not None else slots
        storms = [s for s in considered if s.outlook in STORM_OUTLOOKS]

        alerts: list[WeatherAlert] = []
        if any(s.outlook in HAIL_OUTLOOKS for s in considered):
            alerts.append(WeatherAlert(
                f"heuristic_hail_{suffix}", "orange", "hail", f"Rischio grandine ({label})",
                f"Condizioni compatibili con grandinate {label}.", "heuristic", day=suffix,
            ))
        if any(s.precipitation_intensity in POURING_INTENSITIES for s in storms):
            alerts.append(WeatherAlert(
                f"heuristic_storm_{suffix}", "orange", "storm", f"Temporali forti ({label})",
                f"Previsti temporali forti {label}.", "heuristic", day=suffix,
            ))
        elif storms:
            alerts.append(WeatherAlert(
                f"heuristic_storm_{suffix}", "yellow", "storm", f"Temporali ({label})",
                f"Previsti temporali {label}.", "heuristic", day=suffix,
            ))
        return alerts

    @staticmethod
    def _rain(
        summary: DailyForecast | None, suffix: str, label: str, active: frozenset[str]
    ) -> list[WeatherAlert]:
        prob = summary.precipitation_probability if summary else None
        if prob is None:
            return []
        rain_id = f"heuristic_rain_{suffix}"
        h = RAIN_PROB_HYSTERESIS
        if prob >= RAIN_PROB_YELLOW or (rain_id in active and prob >= RAIN_PROB_YELLOW - h):
            return [WeatherAlert(
                rain_id, "yellow", "rain", f"Piogge probabili ({label})",
                f"Probabilità di precipitazioni {label}: {prob:.0f}%.", "heuristic", day=suffix,
            )]
        return []


# Bollettino di criticità: livello -> (colore, etichetta leggibile)
DPC_LEVEL_SEVERITY = {2: "yellow", 3: "orange", 4: "red"}
DPC_LEVEL_LABEL = {
    2: "Ordinaria criticità",
    3: "Moderata criticità",
    4: "Elevata criticità",
}
DPC_RISK_KIND = {
    "Temporali": "storm",
    "Idraulico": "flood",
    "Idrogeologico": "landslide",
}


class DpcSensorAlertProvider(AlertProvider):
    """Reads the sensor.dpc_alert entity from the DPC Alert custom component
    (github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert), if the
    user has it installed and configured for this location.

    Official Protezione Civile data (CC-BY-SA 4.0), already fetched by that
    other integration — this provider makes no HTTP requests of its own, it
    only reads hass.states.get() on an entity the user points us to.
    """

    name = "protezione_civile"

    def __init__(self, hass: Any, entity_id: str) -> None:
        self.hass = hass
        self.entity_id = entity_id

    async def async_get_alerts(
        self, coordinator_data: Snapshot | None, citta: str, place_name: str,
        active_alert_ids: frozenset[str] | None = None,
    ) -> list[WeatherAlert]:
        state = self.hass.states.get(self.entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return []

        alerts: list[WeatherAlert] = []
        for day_key, day_label in (
            ("events_today", "oggi"),
            ("events_tomorrow", "domani"),
        ):
            for event in state.attributes.get(day_key) or []:
                level = event.get("level")
                severity = DPC_LEVEL_SEVERITY.get(level)
                if severity is None:
                    continue
                risk = event.get("risk", "?")
                level_label = DPC_LEVEL_LABEL.get(level, "Allerta")
                title = f"Protezione Civile: {level_label} per rischio {risk} ({day_label})"
                message = f"Protezione Civile: {level_label} per rischio {risk} — {day_label}."
                alerts.append(WeatherAlert(
                    f"dpc_{risk.lower()}_{day_key}", severity,
                    DPC_RISK_KIND.get(risk, "other"),
                    title,
                    message,
                    "protezione_civile",
                    day="today" if day_key == "events_today" else "tomorrow",
                ))

        # Older versions of the component may not expose events_today/
        # events_tomorrow: fall back to the aggregate today/tomorrow block.
        if not alerts:
            for day_key, day_label in (("today", "oggi"), ("tomorrow", "domani")):
                day = state.attributes.get(day_key)
                if not day:
                    continue
                level = day.get("level")
                severity = DPC_LEVEL_SEVERITY.get(level)
                if severity is None:
                    continue
                level_label = DPC_LEVEL_LABEL.get(level, "Allerta")
                alerts.append(WeatherAlert(
                    f"dpc_{day_key}", severity, "other",
                    f"Protezione Civile: {level_label} ({day_label})",
                    f"Protezione Civile: {level_label} — {day_label}.",
                    "protezione_civile",
                    day=day_key,
                ))

        return alerts


# Fenomeni meteorologici di vigilanza: mappa event -> kind
DPC_VIGILANCE_KIND = {
    "Venti": "wind",
    "Mare": "other",
    "Neve": "snow",
    "Temporali": "storm",
    "Piogge": "rain",
    "Temperature": "heat",
    "Ghiaccio": "cold",
}


class DpcVigilanceProvider(AlertProvider):
    """Reads the sensor.dpc_vigilance entity from the DPC Alert custom component
    (github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert).

    Covers today, tomorrow and aftertomorrow. Each day produces:
    - a level-based alert when level >= 2 (precipitation quantity from the day block)
    - one alert per nearby phenomenon (event, value, distance, direction)

    Complementary to DpcSensorAlertProvider: covers meteorological phenomena
    (wind, snow, storms, etc.) that sensor.dpc_alert does not report.
    """

    name = "protezione_civile_vigilance"

    def __init__(self, hass: Any, entity_id: str) -> None:
        self.hass = hass
        self.entity_id = entity_id

    async def async_get_alerts(
        self, coordinator_data: Snapshot | None, citta: str, place_name: str,
        active_alert_ids: frozenset[str] | None = None,
    ) -> list[WeatherAlert]:
        state = self.hass.states.get(self.entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return []

        alerts: list[WeatherAlert] = []
        for day_key, day_label in (
            ("today", "oggi"),
            ("tomorrow", "domani"),
            ("aftertomorrow", "dopodomani"),
        ):
            day = state.attributes.get(day_key)
            if not day:
                continue

            level = day.get("level")
            day_severity = DPC_LEVEL_SEVERITY.get(level)
            level_label = DPC_LEVEL_LABEL.get(level, "Allerta")

            # Level-based alert for the day block
            if day_severity is not None:
                precip = day.get("precipitation", "")
                message = f"Protezione Civile: {level_label} — vigilanza meteorologica {day_label}"
                if precip:
                    message += f". Precipitazioni: {precip}"
                message += "."
                alerts.append(WeatherAlert(
                    f"dpc_vigilance_{day_key}", day_severity, "rain",
                    f"Protezione Civile: vigilanza meteorologica ({day_label})",
                    message,
                    "protezione_civile_vigilance",
                    day=day_key,
                ))

            if day_severity is None:
                continue

            PHENOMENA_WITH_LOCATION = {"Venti", "Temporali", "Neve", "Mare", "Ghiaccio"}

            for phenom in day.get("phenomena") or []:
                event = phenom.get("event", "")
                value = phenom.get("value", "")
                distance = phenom.get("distance")
                direction = phenom.get("direction", "")
                alert_id = (
                    f"dpc_vigilance_{day_key}_{event.lower().replace(' ', '_')}"
                )
                desc_parts = [f"Protezione Civile: {level_label} — {event} {value}".strip()]
                if event in PHENOMENA_WITH_LOCATION and distance is not None and direction:
                    desc_parts.append(f"a {distance} km in direzione {direction}")
                alerts.append(WeatherAlert(
                    alert_id, day_severity,
                    DPC_VIGILANCE_KIND.get(event, "other"),
                    f"Protezione Civile: {event} {value} ({day_label})".strip(),
                    f"{', '.join(desc_parts)} — {day_label}.",
                    "protezione_civile_vigilance",
                    day=day_key,
                ))

        return alerts

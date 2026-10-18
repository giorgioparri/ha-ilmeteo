"""iLMeteo.it Weather entity (real1 + day1 + tri1 backend)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import sun as sun_helper
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import wind_bearing
from .const import (
    CONF_PLACE_NAME,
    CONF_SITE_NUMBER,
    DEFAULT_INFO_URL,
    DOMAIN,
    map_condition,
)
from .coordinator import IlMeteoCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the weather entity for a config entry."""
    coordinator: IlMeteoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IlMeteoWeather(coordinator, entry)])


def _apply_night(condition: str | None, is_night: bool) -> str | None:
    """Convert 'sunny' and 'partlycloudy' to their night variants when dark.

    iLMeteo's real1 box does not use night codes (>=100) — only tri1 does,
    and even then only sporadically. We apply the correction ourselves using
    HA's sun helper for current conditions, and the slot timestamp for hourly
    forecasts.
    """
    if not is_night or condition is None:
        return condition
    if condition == "sunny":
        return "clear-night"
    return condition


class IlMeteoWeather(CoordinatorEntity[IlMeteoCoordinator], WeatherEntity):
    """Weather entity backed by iLMeteo's real1 + day1 + tri1 boxes."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR
    _attr_attribution = "Dati meteo forniti da iLMeteo.it (www.ilmeteo.it)"
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(
        self, coordinator: IlMeteoCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._place_name = entry.data[CONF_PLACE_NAME]
        self._site_number = entry.data[CONF_SITE_NUMBER]

        # Identity tied to entry_id, not location -> survives reconfigure
        self._attr_unique_id = f"{entry.entry_id}_weather"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"iLMeteo.it {self._place_name}",
            manufacturer="iLMeteo.it",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=self._info_url,
        )

        # Generic entity_id, set directly (only applies on first creation)
        self.entity_id = f"weather.ilmeteo_site_{self._site_number}"

    @property
    def _info_url(self) -> str:
        """Configured municipality's iLMeteo.it page, or the homepage."""
        days = self._days
        if days and days[0].get("url"):
            return days[0]["url"]
        return DEFAULT_INFO_URL

    # ------------------------------------------------------------------
    # Coordinator data accessors
    # ------------------------------------------------------------------

    @property
    def _current(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("current") or {}

    @property
    def _daily(self) -> list[dict[str, Any]]:
        return (self.coordinator.data or {}).get("daily") or []

    @property
    def _days(self) -> list[dict[str, Any]]:
        return (self.coordinator.data or {}).get("days") or []

    # ------------------------------------------------------------------
    # Current conditions (real1)
    # ------------------------------------------------------------------

    @property
    def native_temperature(self) -> float | None:
        return self._current.get("temperature")

    @property
    def humidity(self) -> float | None:
        return self._current.get("humidity")

    @property
    def native_wind_speed(self) -> float | None:
        return self._current.get("wind_speed")

    @property
    def wind_bearing(self) -> float | None:
        return wind_bearing(self._current.get("wind_dir"))

    @property
    def condition(self) -> str | None:
        cur = self._current
        if not cur.get("condition_text") and not cur.get("condition_code"):
            return None
        raw = map_condition(cur.get("condition_text"), cur.get("condition_code"))
        # real1 never uses night codes (>=100) — correct using HA's sun helper.
        return _apply_night(raw, not sun_helper.is_up(self.hass))

    # ------------------------------------------------------------------
    # Forecasts
    # ------------------------------------------------------------------

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Daily forecast: min/max/precip% from day1, precip amount from tri1."""
        daily = self._daily
        days = self._days
        if not daily:
            return None

        forecasts: list[Forecast] = []
        for i, d in enumerate(daily):
            tri_day = days[i] if i < len(days) else None
            precip = None
            if tri_day:
                precip = round(
                    sum(h.get("precipitation") or 0.0 for h in tri_day.get("hours") or []),
                    2,
                )
            date_str = tri_day.get("date") if tri_day else None

            forecasts.append(
                Forecast(
                    datetime=_iso_date(date_str) if date_str else dt_util.now().isoformat(),
                    native_temperature=d.get("temp_max"),
                    native_templow=d.get("temp_min"),
                    native_precipitation=precip,
                    precipitation_probability=d.get("precipitation_probability"),
                    native_wind_speed=d.get("wind_speed"),
                    wind_bearing=wind_bearing(d.get("wind_dir")),
                    # Daily forecasts represent the whole day — no night correction.
                    condition=map_condition(None, d.get("condition_code")),
                )
            )
        return forecasts or None

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """3-hourly forecast from tri1."""
        forecasts: list[Forecast] = []
        for day in self._days:
            for h in day.get("hours") or []:
                dt = _parse_slot_time(day.get("date"), h.get("time"))
                raw = map_condition(
                    h.get("condition_text"), h.get("condition_code")
                )
                # tri1 uses night codes (>=100) when iLMeteo provides them,
                # but not always. Apply the correction from the slot's local
                # time as a reliable fallback.
                is_night = _is_night_at(dt) if dt else False
                forecasts.append(
                    Forecast(
                        datetime=(dt or dt_util.now()).isoformat(),
                        native_temperature=h.get("temperature"),
                        native_apparent_temperature=h.get("wind_chill"),
                        humidity=h.get("humidity"),
                        native_precipitation=h.get("precipitation"),
                        native_wind_speed=h.get("wind_speed"),
                        wind_bearing=wind_bearing(h.get("wind_dir")),
                        condition=_apply_night(raw, is_night),
                    )
                )
        return forecasts or None


# ------------------------------------------------------------------
# Date/time helpers
# ------------------------------------------------------------------

def _iso_date(date_str: str | None) -> str:
    """'DD/MM/YYYY' -> ISO string, labeled local (not converted from UTC)."""
    if not date_str:
        return dt_util.now().isoformat()
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y")
        return dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE).isoformat()
    except ValueError:
        return dt_util.now().isoformat()


def _parse_slot_time(
    date_str: str | None, time_str: str | None
) -> datetime | None:
    """'DD/MM/YYYY' + 'HH.MM' -> local datetime."""
    if not date_str or not time_str:
        return None
    try:
        d = datetime.strptime(date_str, "%d/%m/%Y")
        hour = int(time_str.split(".")[0])
        dt = d.replace(hour=hour, minute=0, second=0, microsecond=0)
        return dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
    except (ValueError, IndexError):
        return None


def _is_night_at(dt: datetime) -> bool:
    """Return True if the given local datetime falls between 21:00 and 06:00.

    A simple time-of-day heuristic — avoids a dependency on ephem or
    real-time astral calculations for forecast slots that may be days away.
    The exact sunrise/sunset varies by season and location but this range
    safely covers astronomical darkness year-round in Italy.
    """
    hour = dt.hour
    return hour >= 21 or hour < 6

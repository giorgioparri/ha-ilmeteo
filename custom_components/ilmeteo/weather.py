"""iLMeteo.it Weather entity (API Gateway backend).

Current conditions come from the hourly slot containing "now" (the gateway's
realtime endpoint answers {} for the time being); day/night comes from the
slot's lightTime, so the 1.x sun-position correction is no longer needed.
Daily forecasts always use the day variant of the condition.
"""
from __future__ import annotations

from datetime import datetime, time

from homeassistant.components.weather import (
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import HourlyForecast
from .const import CONF_PLACE_NAME, CONF_SITE_NUMBER, DOMAIN, outlook_to_condition
from .coordinator import IlMeteoCoordinator
from .quota import QUOTA_TIMEZONE
from .update import Snapshot, dew_point


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the weather entity for a config entry."""
    coordinator: IlMeteoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IlMeteoWeather(coordinator, entry)])


def _km(metres: float | None) -> float | None:
    return round(metres / 1000, 1) if metres is not None else None


class IlMeteoWeather(CoordinatorEntity[IlMeteoCoordinator], WeatherEntity):
    """Weather entity backed by the iLMeteo API Gateway."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_native_precipitation_unit = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_attribution = "Dati meteo forniti da iLMeteo.it (www.ilmeteo.it)"
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_DAILY | WeatherEntityFeature.FORECAST_HOURLY
    )

    def __init__(self, coordinator: IlMeteoCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._place_name = entry.data[CONF_PLACE_NAME]
        self._site_number = entry.data[CONF_SITE_NUMBER]

        # Identity tied to entry_id, not location -> survives reconfigure
        self._attr_unique_id = f"{entry.entry_id}_weather"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"iLMeteo.it {self._place_name}",
            "manufacturer": "iLMeteo.it",
            "entry_type": "service",
            "configuration_url": coordinator.link,
        }

        # Generic entity_id, set directly (only applies on first creation)
        self.entity_id = f"weather.ilmeteo_site_{self._site_number}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Push new forecasts to subscribed cards as well as the state."""
        super()._handle_coordinator_update()
        self.hass.async_create_task(self.async_update_listeners(None))

    # ------------------------------------------------------------------
    # Current conditions: the hourly slot containing "now"
    # ------------------------------------------------------------------

    @property
    def _snapshot(self) -> Snapshot | None:
        return self.coordinator.data

    @property
    def _now(self) -> HourlyForecast | None:
        return self._snapshot.current if self._snapshot else None

    @property
    def condition(self) -> str | None:
        slot = self._now
        if slot is None:
            return None
        return outlook_to_condition(
            slot.outlook, is_night=slot.is_night, intensity=slot.precipitation_intensity
        )

    @property
    def native_temperature(self) -> float | None:
        return self._now.temperature if self._now else None

    @property
    def native_apparent_temperature(self) -> float | None:
        return self._now.apparent_temperature if self._now else None

    @property
    def native_dew_point(self) -> float | None:
        return self._snapshot.dew_point if self._snapshot else None

    @property
    def humidity(self) -> float | None:
        return self._now.humidity if self._now else None

    @property
    def native_pressure(self) -> float | None:
        return self._now.pressure if self._now else None

    @property
    def native_visibility(self) -> float | None:
        return _km(self._now.visibility) if self._now else None

    @property
    def uv_index(self) -> float | None:
        return self._now.uv_index if self._now else None

    @property
    def native_wind_speed(self) -> float | None:
        return self._now.wind_speed if self._now else None

    @property
    def native_wind_gust_speed(self) -> float | None:
        return self._now.wind_gust if self._now else None

    @property
    def wind_bearing(self) -> float | None:
        return self._now.wind_bearing if self._now else None

    # ------------------------------------------------------------------
    # Forecasts
    # ------------------------------------------------------------------

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Daily forecast from today; conditions always in their day variant."""
        if not self._snapshot or not self._snapshot.daily:
            return None
        return [
            Forecast(
                datetime=datetime.combine(
                    day.date, time.min, tzinfo=QUOTA_TIMEZONE
                ).isoformat(),
                condition=outlook_to_condition(
                    day.outlook, intensity=day.precipitation_intensity
                ),
                native_temperature=day.temperature_max,
                native_templow=day.temperature_min,
                native_precipitation=day.precipitation,
                precipitation_probability=(
                    round(day.precipitation_probability)
                    if day.precipitation_probability is not None
                    else None
                ),
                native_pressure=day.pressure,
                native_wind_speed=day.wind_speed,
                native_wind_gust_speed=day.wind_gust,
                wind_bearing=day.wind_bearing,
            )
            for day in self._snapshot.daily
        ]

    async def async_forecast_hourly(self) -> list[Forecast] | None:
        """Hourly forecast from the current hour, about two and a half days."""
        if not self._snapshot or not self._snapshot.hourly:
            return None
        return [
            Forecast(
                datetime=slot.time.isoformat(),
                condition=outlook_to_condition(
                    slot.outlook,
                    is_night=slot.is_night,
                    intensity=slot.precipitation_intensity,
                ),
                native_temperature=slot.temperature,
                native_apparent_temperature=slot.apparent_temperature,
                native_dew_point=dew_point(slot.temperature, slot.humidity),
                humidity=slot.humidity,
                native_precipitation=slot.precipitation,
                native_pressure=slot.pressure,
                native_wind_speed=slot.wind_speed,
                native_wind_gust_speed=slot.wind_gust,
                wind_bearing=slot.wind_bearing,
                uv_index=slot.uv_index,
            )
            for slot in self._snapshot.hourly
        ]

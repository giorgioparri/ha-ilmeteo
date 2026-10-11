"""Optional dedicated sensor entities for iLMeteo.it.

Off by default; enabled via the Options flow or at initial setup. Single-
value snapshots of now (the current hourly slot) or of today (the first
daily row), never the multi-day forecast.

Units are those each sensor had in 1.x: the gateway's m/s are converted to
km/h here, because changing a sensor's native unit makes the recorder flag
its long-term statistics and leaves the user to fix them by hand.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UV_INDEX,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ALL_OPTIONAL_SENSORS,
    CONF_PLACE_NAME,
    CONF_SITE_NUMBER,
    DOMAIN,
    OPT_ENABLED_SENSORS,
    SENSOR_APPARENT_TEMPERATURE,
    SENSOR_DEW_POINT,
    SENSOR_FREEZING_LEVEL,
    SENSOR_HUMIDITY,
    SENSOR_PRECIPITATION_HOUR,
    SENSOR_PRECIPITATION_PROBABILITY,
    SENSOR_PRECIPITATION_TODAY,
    SENSOR_PRESSURE,
    SENSOR_RELIABILITY,
    SENSOR_SNOW_LEVEL,
    SENSOR_TEMPERATURE,
    SENSOR_TEMPERATURE_MAX,
    SENSOR_TEMPERATURE_MIN,
    SENSOR_UV_INDEX,
    SENSOR_VISIBILITY,
    SENSOR_WIND_BEARING,
    SENSOR_WIND_GUST,
    SENSOR_WIND_SPEED,
)
from .coordinator import IlMeteoCoordinator
from .update import Snapshot

_LOGGER = logging.getLogger(__name__)

MS_TO_KMH = 3.6


def _kmh(value: float | None) -> float | None:
    return round(value * MS_TO_KMH, 1) if value is not None else None


def _now(attr: str) -> Callable[[Snapshot], float | None]:
    """Value of a field of the current hourly slot."""
    return lambda s: getattr(s.current, attr) if s.current else None


def _today(attr: str) -> Callable[[Snapshot], float | None]:
    """Value of a field of today's daily row (build_snapshot puts it first)."""
    return lambda s: getattr(s.daily[0], attr) if s.daily else None


@dataclass(frozen=True, slots=True)
class _Spec:
    name: str
    value: Callable[[Snapshot], float | None]
    device_class: SensorDeviceClass | None = None
    unit: str | None = None
    icon: str | None = None


_SENSOR_SPECS: dict[str, _Spec] = {
    # --- 1.x sensors: names, units and classes unchanged ---------------
    SENSOR_TEMPERATURE: _Spec(
        "Temperatura", _now("temperature"),
        SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS,
    ),
    SENSOR_HUMIDITY: _Spec(
        "Umidità", _now("humidity"), SensorDeviceClass.HUMIDITY, PERCENTAGE,
    ),
    SENSOR_WIND_SPEED: _Spec(
        "Velocità del vento",
        lambda s: _kmh(s.current.wind_speed) if s.current else None,
        SensorDeviceClass.WIND_SPEED, UnitOfSpeed.KILOMETERS_PER_HOUR,
    ),
    SENSOR_WIND_BEARING: _Spec(
        "Direzione del vento", _now("wind_bearing"), None, "°", "mdi:compass-outline",
    ),
    SENSOR_TEMPERATURE_MIN: _Spec(
        "Temperatura minima (oggi)", _today("temperature_min"),
        SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS,
    ),
    SENSOR_TEMPERATURE_MAX: _Spec(
        "Temperatura massima (oggi)", _today("temperature_max"),
        SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS,
    ),
    SENSOR_PRECIPITATION_PROBABILITY: _Spec(
        "Probabilità di precipitazioni", _today("precipitation_probability"),
        None, PERCENTAGE, "mdi:weather-rainy",
    ),
    # --- added in 2.0 ---------------------------------------------------
    SENSOR_APPARENT_TEMPERATURE: _Spec(
        "Temperatura percepita", _now("apparent_temperature"),
        SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS,
    ),
    SENSOR_DEW_POINT: _Spec(
        "Punto di rugiada", lambda s: s.dew_point,
        SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS,
    ),
    SENSOR_PRESSURE: _Spec(
        "Pressione", _now("pressure"),
        SensorDeviceClass.ATMOSPHERIC_PRESSURE, UnitOfPressure.HPA,
    ),
    SENSOR_VISIBILITY: _Spec(
        "Visibilità",
        lambda s: (
            round(s.current.visibility / 1000, 1)
            if s.current and s.current.visibility is not None
            else None
        ),
        SensorDeviceClass.DISTANCE, UnitOfLength.KILOMETERS, "mdi:eye-outline",
    ),
    SENSOR_UV_INDEX: _Spec(
        "Indice UV", _now("uv_index"), None, UV_INDEX, "mdi:sun-wireless-outline",
    ),
    SENSOR_WIND_GUST: _Spec(
        "Raffica",
        lambda s: _kmh(s.current.wind_gust) if s.current else None,
        SensorDeviceClass.WIND_SPEED, UnitOfSpeed.KILOMETERS_PER_HOUR,
    ),
    SENSOR_PRECIPITATION_HOUR: _Spec(
        "Precipitazione nell'ora", _now("precipitation"),
        SensorDeviceClass.PRECIPITATION, UnitOfPrecipitationDepth.MILLIMETERS,
    ),
    SENSOR_FREEZING_LEVEL: _Spec(
        "Quota zero termico", _now("freezing_level"),
        SensorDeviceClass.DISTANCE, UnitOfLength.METERS, "mdi:snowflake-thermometer",
    ),
    SENSOR_SNOW_LEVEL: _Spec(
        "Quota neve", _now("snow_level"),
        SensorDeviceClass.DISTANCE, UnitOfLength.METERS, "mdi:snowflake",
    ),
    SENSOR_PRECIPITATION_TODAY: _Spec(
        "Precipitazione totale (oggi)", _today("precipitation"),
        SensorDeviceClass.PRECIPITATION, UnitOfPrecipitationDepth.MILLIMETERS,
    ),
    SENSOR_RELIABILITY: _Spec(
        "Affidabilità previsione (oggi)", _today("reliability"),
        None, PERCENTAGE, "mdi:check-decagram-outline",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add enabled sensors, remove deselected ones."""
    coordinator: IlMeteoCoordinator = hass.data[DOMAIN][entry.entry_id]
    enabled = set(entry.options.get(OPT_ENABLED_SENSORS, []))

    entities = [
        IlMeteoSensor(coordinator, entry, sensor_type)
        for sensor_type in ALL_OPTIONAL_SENSORS
        if sensor_type in enabled
    ]
    if entities:
        async_add_entities(entities)

    # Remove any deselected sensor (deselect = delete, not just unavailable)
    registry = er.async_get(hass)
    for sensor_type in ALL_OPTIONAL_SENSORS:
        if sensor_type in enabled:
            continue
        unique_id = f"{entry.entry_id}_{sensor_type}"
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if entity_id:
            _LOGGER.debug("Removing deselected sensor %s", entity_id)
            registry.async_remove(entity_id)


class IlMeteoSensor(CoordinatorEntity[IlMeteoCoordinator], SensorEntity):
    """A single optional dedicated sensor (temperature, humidity, ...)."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: IlMeteoCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._spec = _SENSOR_SPECS[sensor_type]
        place_name = entry.data[CONF_PLACE_NAME]
        site_number = entry.data[CONF_SITE_NUMBER]

        self._attr_name = self._spec.name
        self._attr_device_class = self._spec.device_class
        self._attr_native_unit_of_measurement = self._spec.unit
        self._attr_icon = self._spec.icon

        # Same device identifiers as the weather entity -> groups together
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"iLMeteo.it {place_name}",
            "manufacturer": "iLMeteo.it",
            "entry_type": "service",
            "configuration_url": coordinator.link,
        }

        # Generic entity_id, set directly (only applies on first creation)
        self.entity_id = f"sensor.ilmeteo_site_{site_number}_{sensor_type}"

    @property
    def native_value(self) -> float | None:
        snapshot = self.coordinator.data
        return self._spec.value(snapshot) if snapshot else None

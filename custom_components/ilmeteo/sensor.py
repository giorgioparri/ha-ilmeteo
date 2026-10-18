"""Optional dedicated sensor entities for iLMeteo.it.

Off by default; enabled via the Options flow or at initial setup. Single-
value snapshots of today only (current reading or day1 row 0), never the
multi-day forecast.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import wind_bearing
from .const import (
    ALL_OPTIONAL_SENSORS,
    CONF_PLACE_NAME,
    CONF_SITE_NUMBER,
    DEFAULT_INFO_URL,
    DOMAIN,
    OPT_ENABLED_SENSORS,
    SENSOR_HUMIDITY,
    SENSOR_PRECIPITATION_PROBABILITY,
    SENSOR_TEMPERATURE,
    SENSOR_TEMPERATURE_MAX,
    SENSOR_TEMPERATURE_MIN,
    SENSOR_WIND_BEARING,
    SENSOR_WIND_SPEED,
)
from .coordinator import IlMeteoCoordinator

_LOGGER = logging.getLogger(__name__)

# name, device_class, unit, icon per sensor type
_SENSOR_SPECS: dict[str, dict[str, Any]] = {
    SENSOR_TEMPERATURE: {
        "name": "Temperatura",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": None,
    },
    SENSOR_HUMIDITY: {
        "name": "Umidità",
        "device_class": SensorDeviceClass.HUMIDITY,
        "unit": PERCENTAGE,
        "icon": None,
    },
    SENSOR_WIND_SPEED: {
        "name": "Velocità del vento",
        "device_class": SensorDeviceClass.WIND_SPEED,
        "unit": UnitOfSpeed.KILOMETERS_PER_HOUR,
        "icon": None,
    },
    SENSOR_WIND_BEARING: {
        "name": "Direzione del vento",
        "device_class": None,
        "unit": "°",
        "icon": "mdi:compass-outline",
    },
    SENSOR_TEMPERATURE_MIN: {
        "name": "Temperatura minima (oggi)",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": None,
    },
    SENSOR_TEMPERATURE_MAX: {
        "name": "Temperatura massima (oggi)",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": None,
    },
    SENSOR_PRECIPITATION_PROBABILITY: {
        "name": "Probabilità di precipitazioni",
        "device_class": None,
        "unit": PERCENTAGE,
        "icon": "mdi:weather-rainy",
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add enabled sensors, remove deselected ones."""
    coordinator: IlMeteoCoordinator = hass.data[DOMAIN][entry.entry_id]
    enabled = set(entry.options.get(OPT_ENABLED_SENSORS, []))

    # Add currently-enabled sensors
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
        self._sensor_type = sensor_type
        place_name = entry.data[CONF_PLACE_NAME]
        site_number = entry.data[CONF_SITE_NUMBER]

        spec = _SENSOR_SPECS[sensor_type]
        self._attr_name = spec["name"]
        self._attr_device_class = spec["device_class"]
        self._attr_native_unit_of_measurement = spec["unit"]
        self._attr_icon = spec["icon"]

        # Same device identifiers as the weather entity -> groups together
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"iLMeteo.it {place_name}",
            manufacturer="iLMeteo.it",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=self._info_url,
        )

        # Generic entity_id, set directly (only applies on first creation)
        self.entity_id = f"sensor.ilmeteo_site_{site_number}_{sensor_type}"

    @property
    def _info_url(self) -> str:
        """Configured municipality's iLMeteo.it page, or the homepage."""
        days = (self.coordinator.data or {}).get("days") or []
        if days and days[0].get("url"):
            return days[0]["url"]
        return DEFAULT_INFO_URL

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data or {}
        current = data.get("current") or {}
        daily = data.get("daily") or []
        today = daily[0] if daily else {}

        if self._sensor_type == SENSOR_TEMPERATURE:
            return current.get("temperature")
        if self._sensor_type == SENSOR_HUMIDITY:
            return current.get("humidity")
        if self._sensor_type == SENSOR_WIND_SPEED:
            return current.get("wind_speed")
        if self._sensor_type == SENSOR_WIND_BEARING:
            return wind_bearing(current.get("wind_dir"))
        if self._sensor_type == SENSOR_TEMPERATURE_MIN:
            return today.get("temp_min")
        if self._sensor_type == SENSOR_TEMPERATURE_MAX:
            return today.get("temp_max")
        if self._sensor_type == SENSOR_PRECIPITATION_PROBABILITY:
            return today.get("precipitation_probability")
        return None

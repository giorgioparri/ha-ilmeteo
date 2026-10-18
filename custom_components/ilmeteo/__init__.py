"""The iLMeteo.it integration (API Gateway backend)."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .alert_manager import IlMeteoAlertManager
from .client import IlMeteoClient
from .const import (
    CONF_API_KEY,
    CONF_CITTA,
    CONF_PLACE_NAME,
    CONF_UPGRADED_FROM_1X,
    DEFAULT_ALERT_NOTIFICATIONS,
    DOMAIN,
    OPT_ALERT_NOTIFICATIONS,
    OPT_DPC_ALERT_ENTITY,
    OPT_DPC_VIGILANCE_ENTITY,
    OPT_NOTIFY_TARGETS,
)
from .coordinator import IlMeteoCoordinator, async_get_key_runtime

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.WEATHER, Platform.SENSOR]

# Keyed separately from hass.data[DOMAIN] (which holds coordinators, keyed by
# entry_id, and is relied upon as-is by weather.py/sensor.py/diagnostics.py).
_ALERT_MANAGERS_KEY = f"{DOMAIN}_alert_managers"
_RELOAD_STATE_KEY = f"{DOMAIN}_reload_state"

# Repair issues raised by the 1.x box scraper, one per location and box.
_SCRAPER_BOXES = ("real1", "day1", "tri1")

# One-time notices, shown once per installation.
_NOTICES_STORAGE_VERSION = 1
_NOTICES_STORAGE_KEY = f"{DOMAIN}_notices"
_NOTICE_NEW_SENSORS = "new_sensors_2_0"


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate entries created by the 1.x box scraper (version 3) to 2.0.

    The gateway's place ids are the codes the scraper used, suppressed comuni
    and hamlets included, so the location is kept as is. Only the API key is
    missing: setup then raises ConfigEntryAuthFailed and Home Assistant asks
    for it; entering it once serves every location (config_flow reauth).
    """
    if entry.version > 4:
        return False  # downgrade from a future version
    if entry.version < 4:
        _LOGGER.info(
            "Migrating iLMeteo entry %s from version %s to 4", entry.title, entry.version
        )
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_UPGRADED_FROM_1X: True},
            version=4,
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iLMeteo.it from a config entry."""
    api_key = entry.data.get(CONF_API_KEY)
    if not api_key:
        raise ConfigEntryAuthFailed("An iLMeteo.it API key is required")

    runtime = await async_get_key_runtime(hass, api_key)
    client = IlMeteoClient(
        async_get_clientsession(hass), api_key, on_request=runtime.record_request
    )
    coordinator = IlMeteoCoordinator(hass, entry, client, runtime)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    _clear_scraper_issues(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if entry.options.get(OPT_ALERT_NOTIFICATIONS, DEFAULT_ALERT_NOTIFICATIONS):
        alert_manager = IlMeteoAlertManager(
            hass=hass,
            coordinator=coordinator,
            entry_id=entry.entry_id,
            citta=str(entry.data[CONF_CITTA]),
            place_name=entry.data[CONF_PLACE_NAME],
            link=coordinator.link,
            dpc_entity_id=entry.options.get(OPT_DPC_ALERT_ENTITY) or None,
            dpc_vigilance_entity_id=entry.options.get(OPT_DPC_VIGILANCE_ENTITY) or None,
            notify_targets=entry.options.get(OPT_NOTIFY_TARGETS) or [],
        )
        await alert_manager.async_start()
        hass.data.setdefault(_ALERT_MANAGERS_KEY, {})[entry.entry_id] = alert_manager

    if entry.data.get(CONF_UPGRADED_FROM_1X):
        await _async_notify_new_sensors(hass)
        hass.config_entries.async_update_entry(
            entry,
            data={k: v for k, v in entry.data.items() if k != CONF_UPGRADED_FROM_1X},
        )

    # Reload when the user changes options or the display name. Data the
    # integration writes itself (the place's gateway name, the marker above)
    # must not restart the entry and spend two more requests.
    hass.data.setdefault(_RELOAD_STATE_KEY, {})[entry.entry_id] = _reload_state(entry)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


def _reload_state(entry: ConfigEntry) -> tuple:
    return (dict(entry.options), entry.data.get(CONF_PLACE_NAME))


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry after its options or display name change."""
    if hass.data.get(_RELOAD_STATE_KEY, {}).get(entry.entry_id) != _reload_state(entry):
        await hass.config_entries.async_reload(entry.entry_id)


def _clear_scraper_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove repair issues the 1.x scraper may have left open."""
    citta = str(entry.data[CONF_CITTA])
    for box in _SCRAPER_BOXES:
        ir.async_delete_issue(hass, DOMAIN, f"box_parse_error_{citta}_{box}")


async def _async_notify_new_sensors(hass: HomeAssistant) -> None:
    """Tell users upgrading from 1.x about the new optional sensors, once."""
    store: Store[dict[str, bool]] = Store(
        hass, _NOTICES_STORAGE_VERSION, _NOTICES_STORAGE_KEY
    )
    shown = await store.async_load() or {}
    if shown.get(_NOTICE_NEW_SENSORS):
        return
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "notification_id": f"{DOMAIN}_{_NOTICE_NEW_SENSORS}",
            "title": "iLMeteo.it 2.0: nuovi sensori disponibili",
            "message": (
                "L'integrazione ora usa le API ufficiali di iLMeteo.it e offre "
                "nuovi sensori opzionali: temperatura percepita, punto di "
                "rugiada, pressione, visibilità, indice UV, irraggiamento "
                "solare stimato, raffica, precipitazione nell'ora e totale del "
                "giorno, quota dello zero termico, quota neve e affidabilità "
                "della previsione.\n\n"
                "Per attivarli: Impostazioni → Dispositivi e servizi → "
                "iLMeteo.it → Configura, per ogni località."
            ),
        },
        blocking=False,
    )
    await store.async_save({**shown, _NOTICE_NEW_SENSORS: True})


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.data.get(_RELOAD_STATE_KEY, {}).pop(entry.entry_id, None)
        alert_manager = hass.data.get(_ALERT_MANAGERS_KEY, {}).pop(entry.entry_id, None)
        if alert_manager is not None:
            alert_manager.async_stop()
    return unload_ok

"""Diagnostics support for the iLMeteo.it integration.

The API key is redacted: diagnostics are meant to be attached to public
issues. The key's fingerprint is kept, so two locations sharing a key can be
recognized without revealing it.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, DOMAIN
from .coordinator import IlMeteoCoordinator

TO_REDACT = {CONF_API_KEY}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Entry data, key status, quota and the snapshot the entities show."""
    coordinator: IlMeteoCoordinator = hass.data[DOMAIN][entry.entry_id]
    runtime = coordinator.runtime
    snapshot = coordinator.data

    return {
        "config_entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "key_fingerprint": runtime.fingerprint,
        "key_status": runtime.status.as_dict(),
        "quota": runtime.tracker.as_dict(),
        "last_update_success": coordinator.last_update_success,
        "last_exception": (
            str(coordinator.last_exception) if coordinator.last_exception else None
        ),
        "link": coordinator.link,
        "snapshot": asdict(snapshot) if snapshot else None,
    }

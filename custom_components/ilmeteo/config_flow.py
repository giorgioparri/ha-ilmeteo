"""Config flow for the iLMeteo.it integration.

Setup: API key -> how to pick the place (near home, search by name, or
region -> province -> place) -> details. Reconfigure changes the place only,
with the same three ways of picking it. Reauth asks for the key alone and
passes it on to the other locations still waiting for one. Options change
the display name, the optional sensors and the alert settings.

Every request made here counts against the key's daily quota, exactly as
the coordinator's do: the client is built with the key's shared counter.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .client import (
    IlMeteoAuthError,
    IlMeteoClient,
    IlMeteoError,
    IlMeteoOutOfScope,
    IlMeteoQuotaExceeded,
    Place,
    Province,
    Region,
    normalize_key,
)
from .const import (
    ALL_OPTIONAL_SENSORS,
    CONF_API_KEY,
    CONF_CITTA,
    CONF_GATEWAY_NAME,
    CONF_PLACE_NAME,
    CONF_SITE_NUMBER,
    DEFAULT_ALERT_NOTIFICATIONS,
    DOMAIN,
    OPT_ALERT_NOTIFICATIONS,
    OPT_DPC_ALERT_ENTITY,
    OPT_DPC_VIGILANCE_ENTITY,
    OPT_ENABLED_SENSORS,
    OPT_NOTIFY_TARGETS,
)
from .coordinator import async_get_key_runtime

_LOGGER = logging.getLogger(__name__)

CONF_REGION = "region"
CONF_PROVINCE = "province"
CONF_PLACE = "place"
CONF_QUERY = "query"
CONF_NAME = "name"

METHOD_NEARBY = "nearby"
METHOD_SEARCH = "search"
METHOD_BROWSE = "region"


# ---------------------------------------------------------------------------
# Selectors shared by setup and options
# ---------------------------------------------------------------------------

def _sensor_selector() -> selector.SelectSelector:
    """Multi-select checklist of optional sensors; labels from translations."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=list(ALL_OPTIONAL_SENSORS),
            multiple=True,
            mode=selector.SelectSelectorMode.LIST,
            translation_key="optional_sensors",
        )
    )


def _dpc_entity_selector() -> selector.EntitySelector:
    """Picker for the DPC Alert integration's sensors. Leave blank if absent."""
    return selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))


def _notify_targets_selector(hass: Any) -> selector.SelectSelector:
    """Multi-select of available notify.mobile_app_* services.

    Built at runtime so the list reflects the devices actually registered
    in this HA instance. EntitySelector with integration='mobile_app' does
    not filter correctly; iterating hass.services is the reliable approach.
    """
    services = hass.services.async_services().get("notify", {})
    options = [
        selector.SelectOptionDict(value=f"notify.{name}", label=f"notify.{name}")
        for name in sorted(services)
        if name.startswith("mobile_app_")
    ]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _key_selector() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
    )


def _clean_options(user_input: dict[str, Any]) -> dict[str, Any]:
    """Sanitize options before saving to config entry.

    EntitySelector with no selection returns None, which then fails HA's
    entity-ID validation on the next form load. Normalize to a safe default.
    """
    return {
        OPT_ENABLED_SENSORS: user_input.get(OPT_ENABLED_SENSORS) or [],
        OPT_ALERT_NOTIFICATIONS: user_input.get(
            OPT_ALERT_NOTIFICATIONS, DEFAULT_ALERT_NOTIFICATIONS
        ),
        OPT_DPC_ALERT_ENTITY: user_input.get(OPT_DPC_ALERT_ENTITY) or None,
        OPT_DPC_VIGILANCE_ENTITY: user_input.get(OPT_DPC_VIGILANCE_ENTITY) or None,
        OPT_NOTIFY_TARGETS: user_input.get(OPT_NOTIFY_TARGETS) or [],
    }


# ---------------------------------------------------------------------------
# Place lists
# ---------------------------------------------------------------------------

def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine), in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def _place_options(
    places: list[Place], origin: tuple[float, float] | None = None
) -> list[selector.SelectOptionDict]:
    """One option per place: name, province, distance, borrowed forecast.

    A place whose forecast is another place's (realId, e.g. Roma Testaccio
    -> Roma) says so, so nobody believes they get district-level data that
    the gateway does not have.
    """
    names = {p.id: p.name for p in places}
    options = []
    for place in places:
        label = place.name
        if place.province:
            label += f" ({place.province})"
        if origin and place.latitude is not None and place.longitude is not None:
            km = _distance_km(origin[0], origin[1], place.latitude, place.longitude)
            label += f" · {km:.0f} km"
        if place.is_alias:
            parent = names.get(place.real_id)
            label += f" — previsione di {parent}" if parent else " — previsione del comune"
        options.append(selector.SelectOptionDict(value=str(place.id), label=label))
    return options


def _place_selector(options: list[selector.SelectOptionDict]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _error_key(err: IlMeteoError) -> str:
    """Form error for a failed gateway request."""
    if isinstance(err, IlMeteoAuthError):
        return "invalid_auth"
    if isinstance(err, IlMeteoQuotaExceeded):
        return "quota_exceeded"
    if isinstance(err, IlMeteoOutOfScope):
        return "out_of_scope"
    return "cannot_connect"


_SITE_COUNTER_STORAGE_VERSION = 1
_SITE_COUNTER_STORAGE_KEY = f"{DOMAIN}_site_counter"


async def _next_site_number(hass: Any) -> int:
    """Next site number; persisted independently of existing entries
    so numbers are never reused."""
    store: Store[dict] = Store(
        hass, _SITE_COUNTER_STORAGE_VERSION, _SITE_COUNTER_STORAGE_KEY
    )
    data = await store.async_load() or {"highest": 0}
    next_number = data["highest"] + 1
    await store.async_save({"highest": next_number})
    return next_number


class IlMeteoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Key -> way of picking -> place -> details."""

    VERSION = 4

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._regions: list[Region] = []
        self._region: str | None = None
        self._provinces: list[Province] = []
        self._places: list[Place] = []
        self._place: Place | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Return the Options flow for this entry."""
        return OptionsFlowHandler(config_entry)

    # ------------------------------------------------------------------
    # Gateway access
    # ------------------------------------------------------------------

    async def _client(self) -> IlMeteoClient | None:
        """Client counting against the key's quota; None while it is blocked."""
        runtime = await async_get_key_runtime(self.hass, self._api_key)
        if runtime.tracker.is_blocked(dt_util.now()):
            return None
        return IlMeteoClient(
            async_get_clientsession(self.hass),
            self._api_key,
            on_request=runtime.record_request,
        )

    async def _call(self, method: str, *args: Any) -> tuple[Any, str | None]:
        """Run a client method; return (result, form error key or None)."""
        client = await self._client()
        if client is None:
            return None, "quota_exceeded"
        try:
            return await getattr(client, method)(*args), None
        except IlMeteoError as err:
            _LOGGER.warning("iLMeteo %s failed: %s", method, err)
            if isinstance(err, IlMeteoQuotaExceeded):
                runtime = await async_get_key_runtime(self.hass, self._api_key)
                runtime.tracker.block(dt_util.now())
                runtime.schedule_save()
            return None, _error_key(err)

    def _existing_key(self) -> str | None:
        """Key of an already configured location, offered as default."""
        for entry in self._async_current_entries():
            if entry.data.get(CONF_API_KEY):
                return entry.data[CONF_API_KEY]
        return None

    # ------------------------------------------------------------------
    # Initial setup: key
    # ------------------------------------------------------------------

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: the API key from the user's iLMeteo.it account.

        Checked by downloading the list of regions, which the region ->
        province -> place path needs anyway.
        """
        errors: dict[str, str] = {}
        if user_input is not None:
            self._api_key = normalize_key(user_input[CONF_API_KEY])
            regions, error = await self._call("async_get_regions")
            if error:
                errors["base"] = error
            else:
                self._regions = regions
                return await self.async_step_method()

        default = self._existing_key()
        key_field = (
            vol.Required(CONF_API_KEY, default=default)
            if default
            else vol.Required(CONF_API_KEY)
        )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({key_field: _key_selector()}),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Picking the place (shared by setup and reconfigure)
    # ------------------------------------------------------------------

    async def async_step_method(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """How to pick the place."""
        return self.async_show_menu(
            step_id="method",
            menu_options=[METHOD_NEARBY, METHOD_SEARCH, METHOD_BROWSE],
        )

    async def async_step_nearby(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Places around Home Assistant's home location, nearest first."""
        if user_input is not None:
            return await self._async_place_chosen(user_input[CONF_PLACE])

        origin = (self.hass.config.latitude, self.hass.config.longitude)
        places, error = await self._call("async_nearby", *origin)
        if error:
            return self.async_abort(reason=error)
        if not places:
            return self.async_abort(reason="no_places_nearby")
        self._places = places
        return self.async_show_form(
            step_id="nearby",
            data_schema=vol.Schema(
                {vol.Required(CONF_PLACE): _place_selector(_place_options(places, origin))}
            ),
        )

    async def async_step_search(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Free-text search by name (issue #1: districts such as Roma Testaccio)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            query = user_input[CONF_QUERY].strip()
            if len(query) < 2:
                errors[CONF_QUERY] = "query_too_short"
            else:
                places, error = await self._call("async_search", query)
                if error:
                    errors["base"] = error
                elif not places:
                    errors[CONF_QUERY] = "no_results"
                else:
                    self._places = places
                    return await self.async_step_search_results()

        return self.async_show_form(
            step_id="search",
            data_schema=vol.Schema({vol.Required(CONF_QUERY): str}),
            errors=errors,
        )

    async def async_step_search_results(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_place_chosen(user_input[CONF_PLACE])
        return self.async_show_form(
            step_id="search_results",
            data_schema=vol.Schema(
                {vol.Required(CONF_PLACE): _place_selector(_place_options(self._places))}
            ),
        )

    async def async_step_region(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Browse: region."""
        if user_input is not None:
            self._region = user_input[CONF_REGION]
            return await self.async_step_province()

        if not self._regions:
            regions, error = await self._call("async_get_regions")
            if error:
                return self.async_abort(reason=error)
            self._regions = regions
        options = [
            selector.SelectOptionDict(value=r.id, label=r.name) for r in self._regions
        ]
        return self.async_show_form(
            step_id="region",
            data_schema=vol.Schema({vol.Required(CONF_REGION): _place_selector(options)}),
        )

    async def async_step_province(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Browse: province."""
        if user_input is not None:
            places, error = await self._call(
                "async_get_places", self._region, user_input[CONF_PROVINCE]
            )
            if error:
                return self.async_abort(reason=error)
            self._places = sorted(places, key=lambda p: p.name)
            return await self.async_step_place()

        provinces, error = await self._call("async_get_provinces", self._region)
        if error:
            return self.async_abort(reason=error)
        self._provinces = provinces
        options = [
            selector.SelectOptionDict(value=p.id, label=f"{p.name} ({p.id})")
            for p in provinces
        ]
        return self.async_show_form(
            step_id="province",
            data_schema=vol.Schema({vol.Required(CONF_PROVINCE): _place_selector(options)}),
        )

    async def async_step_place(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Browse: place, hamlets and districts included."""
        if user_input is not None:
            return await self._async_place_chosen(user_input[CONF_PLACE])
        return self.async_show_form(
            step_id="place",
            data_schema=vol.Schema(
                {vol.Required(CONF_PLACE): _place_selector(_place_options(self._places))}
            ),
        )

    async def _async_place_chosen(self, place_id: str) -> ConfigFlowResult:
        place = next((p for p in self._places if str(p.id) == place_id), None)
        if place is None:
            return self.async_abort(reason="invalid_place")
        self._place = place

        if self.source == config_entries.SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            if any(
                e.entry_id != entry.entry_id and e.data.get(CONF_CITTA) == str(place.id)
                for e in self._async_current_entries()
            ):
                return self.async_abort(reason="already_configured")
            return self.async_update_reload_and_abort(
                entry,
                unique_id=f"{DOMAIN}_{place.id}",
                title=place.name,
                data_updates={
                    CONF_CITTA: str(place.id),
                    CONF_GATEWAY_NAME: place.name,
                    CONF_PLACE_NAME: place.name,
                },
            )

        await self.async_set_unique_id(f"{DOMAIN}_{place.id}")
        self._abort_if_unique_id_configured()
        return await self.async_step_details()

    # ------------------------------------------------------------------
    # Initial setup: details
    # ------------------------------------------------------------------

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Display name, optional sensors and alerts."""
        place = self._place
        if user_input is not None:
            name = user_input.get(CONF_NAME) or place.name
            site_number = await _next_site_number(self.hass)
            return self.async_create_entry(
                title=name,
                data={
                    CONF_API_KEY: self._api_key,
                    CONF_CITTA: str(place.id),
                    CONF_GATEWAY_NAME: place.name,
                    CONF_PLACE_NAME: name,
                    CONF_SITE_NUMBER: site_number,
                },
                options=_clean_options(user_input),
            )

        return self.async_show_form(
            step_id="details",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default=place.name): str,
                    vol.Optional(OPT_ENABLED_SENSORS, default=[]): _sensor_selector(),
                    vol.Optional(
                        OPT_ALERT_NOTIFICATIONS, default=DEFAULT_ALERT_NOTIFICATIONS
                    ): selector.BooleanSelector(),
                    vol.Optional(OPT_DPC_ALERT_ENTITY, default=vol.UNDEFINED): _dpc_entity_selector(),
                    vol.Optional(OPT_DPC_VIGILANCE_ENTITY, default=vol.UNDEFINED): _dpc_entity_selector(),
                    vol.Optional(
                        OPT_NOTIFY_TARGETS, default=[]
                    ): _notify_targets_selector(self.hass),
                }
            ),
            description_placeholders={"place": place.name},
        )

    # ------------------------------------------------------------------
    # Reconfigure: place only; key, name option, sensors untouched
    # ------------------------------------------------------------------

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        self._api_key = entry.data.get(CONF_API_KEY)
        if not self._api_key:
            return self.async_abort(reason="missing_api_key")
        return await self.async_step_method()

    # ------------------------------------------------------------------
    # Reauth: the key alone
    # ------------------------------------------------------------------

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Started by ConfigEntryAuthFailed, or by an entry migrated from 1.x."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            self._api_key = normalize_key(user_input[CONF_API_KEY])
            place, error = await self._call("async_get_place", int(entry.data[CONF_CITTA]))
            if error:
                errors["base"] = error
            elif place is None:
                errors["base"] = "invalid_place"
            else:
                self._share_key_with_waiting_entries(entry)
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_API_KEY: self._api_key,
                        CONF_GATEWAY_NAME: place.name,
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): _key_selector()}),
            errors=errors,
            description_placeholders={"place": entry.data.get(CONF_PLACE_NAME, "")},
        )

    def _share_key_with_waiting_entries(self, current: config_entries.ConfigEntry) -> None:
        """Give the new key to the other locations without one or with the old one.

        After a migration from 1.x every location asks for the key: entering
        it once is enough. Their pending reauth flows are closed.
        """
        old_key = current.data.get(CONF_API_KEY)
        for entry in self._async_current_entries():
            if entry.entry_id == current.entry_id:
                continue
            key = entry.data.get(CONF_API_KEY)
            if key and key != old_key:
                continue
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_API_KEY: self._api_key}
            )
            for flow in self.hass.config_entries.flow.async_progress_by_handler(DOMAIN):
                if (
                    flow["flow_id"] != self.flow_id
                    and flow["context"].get("source") == config_entries.SOURCE_REAUTH
                    and flow["context"].get("entry_id") == entry.entry_id
                ):
                    self.hass.config_entries.flow.async_abort(flow["flow_id"])
            self.hass.config_entries.async_schedule_reload(entry.entry_id)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow: display name, enabled sensors, alerts."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            new_name = user_input.get(CONF_NAME) or self._entry.data[CONF_PLACE_NAME]

            if new_name != self._entry.data.get(CONF_PLACE_NAME):
                self.hass.config_entries.async_update_entry(
                    self._entry,
                    title=new_name,
                    data={**self._entry.data, CONF_PLACE_NAME: new_name},
                )

            return self.async_create_entry(title="", data=_clean_options(user_input))

        current_name = self._entry.data.get(CONF_PLACE_NAME, "")
        current_sensors = [
            s for s in self._entry.options.get(OPT_ENABLED_SENSORS, [])
            if s in ALL_OPTIONAL_SENSORS
        ]
        current_alerts = self._entry.options.get(
            OPT_ALERT_NOTIFICATIONS, DEFAULT_ALERT_NOTIFICATIONS
        )
        current_dpc_entity = self._entry.options.get(OPT_DPC_ALERT_ENTITY) or vol.UNDEFINED
        current_dpc_vigilance = self._entry.options.get(OPT_DPC_VIGILANCE_ENTITY) or vol.UNDEFINED
        current_notify_targets = self._entry.options.get(OPT_NOTIFY_TARGETS, [])
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_NAME, default=current_name): str,
                    vol.Optional(
                        OPT_ENABLED_SENSORS, default=current_sensors
                    ): _sensor_selector(),
                    vol.Optional(
                        OPT_ALERT_NOTIFICATIONS, default=current_alerts
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        OPT_DPC_ALERT_ENTITY, default=current_dpc_entity
                    ): _dpc_entity_selector(),
                    vol.Optional(
                        OPT_DPC_VIGILANCE_ENTITY, default=current_dpc_vigilance
                    ): _dpc_entity_selector(),
                    vol.Optional(
                        OPT_NOTIFY_TARGETS, default=current_notify_targets
                    ): _notify_targets_selector(self.hass),
                }
            ),
        )

"""DataUpdateCoordinator for iLMeteo.it (API Gateway).

Every decision lives in update.py and is tested there; this module wires it
to Home Assistant:

- KeyRuntime: what is shared by every location using the same API key, i.e.
  the daily quota and what the gateway has told us about the key. Persisted
  with HA's Store so a restart during a block does not burn requests on a
  key the gateway is already refusing.
- IlMeteoCoordinator: one per location. Each cycle asks plan_update which
  endpoints may be called, keeps the last downloaded lists as a cache and
  projects them onto "now" with build_snapshot, so the entities keep
  advancing hour by hour even when no request can be sent.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .client import (
    DailyForecast,
    HourlyForecast,
    IlMeteoClient,
    IlMeteoError,
)
from .const import (
    CONF_CITTA,
    CONF_GATEWAY_NAME,
    CONF_PLACE_NAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    place_page_url,
)
from .quota import QuotaTracker
from .update import (
    ENDPOINT_DAILY,
    ENDPOINT_HOURLY,
    Action,
    KeyStatus,
    Notice,
    Snapshot,
    build_snapshot,
    plan_update,
    request_window,
)

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1
_SAVE_DELAY = 10  # seconds: coalesce the writes of several locations
_KEYS = f"{DOMAIN}_keys"


def key_fingerprint(api_key: str) -> str:
    """Short, non-reversible identifier of a key, for storage and notification ids."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


class KeyRuntime:
    """Quota and key status shared by every location using the same key."""

    def __init__(self, hass: HomeAssistant, api_key: str) -> None:
        self.hass = hass
        self.fingerprint = key_fingerprint(api_key)
        self.tracker = QuotaTracker()
        self.status = KeyStatus()
        self._store: Store[dict[str, Any]] = Store(
            hass, _STORAGE_VERSION, f"{DOMAIN}_key_{self.fingerprint}"
        )

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self.tracker = QuotaTracker.from_dict(data.get("quota"))
        self.status = KeyStatus.from_dict(data.get("status"))

    def schedule_save(self) -> None:
        self._store.async_delay_save(
            lambda: {"quota": self.tracker.as_dict(), "status": self.status.as_dict()},
            _SAVE_DELAY,
        )

    def record_request(self) -> None:
        """Count a request sent now; passed to the client as on_request."""
        self.tracker.record_request(dt_util.now())

    # --- persistent notifications, one per key and kind ------------------

    def _notification_id(self, notice: Notice) -> str:
        return f"{DOMAIN}_{notice}_{self.fingerprint}"

    def notify(self, notice: Notice, detail: str = "") -> None:
        if notice is Notice.QUOTA:
            resume = self.tracker.blocked_until
            when = (
                dt_util.as_local(resume).strftime("%H:%M del %d/%m")
                if resume
                else "dopo la mezzanotte"
            )
            title = "iLMeteo.it: limite giornaliero raggiunto"
            message = (
                "La chiave API ha esaurito le richieste di oggi. Le previsioni "
                "mostrate sono le ultime scaricate e continuano ad avanzare ora "
                f"per ora; gli aggiornamenti riprendono alle {when}."
            )
        else:
            title = "iLMeteo.it: chiave API rifiutata"
            message = (
                "iLMeteo.it ha rifiutato la chiave API con un messaggio non "
                f"riconosciuto ({detail or 'nessun dettaglio'}). Le previsioni "
                "mostrate sono le ultime scaricate. Se il problema dura 24 ore "
                "verrà chiesto di reinserire la chiave."
            )
        self.hass.async_create_task(
            self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "notification_id": self._notification_id(notice),
                    "title": title,
                    "message": message,
                },
                blocking=False,
            )
        )

    def dismiss(self) -> None:
        for notice in Notice:
            self.hass.async_create_task(
                self.hass.services.async_call(
                    "persistent_notification",
                    "dismiss",
                    {"notification_id": self._notification_id(notice)},
                    blocking=False,
                )
            )


async def async_get_key_runtime(hass: HomeAssistant, api_key: str) -> KeyRuntime:
    """Return the runtime for a key, loading it from storage the first time."""
    runtimes: dict[str, KeyRuntime] = hass.data.setdefault(_KEYS, {})
    fingerprint = key_fingerprint(api_key)
    if fingerprint not in runtimes:
        runtime = KeyRuntime(hass, api_key)
        await runtime.async_load()
        runtimes[fingerprint] = runtime
    return runtimes[fingerprint]


class IlMeteoCoordinator(DataUpdateCoordinator[Snapshot]):
    """Fetches the daily and hourly forecast of one location."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: IlMeteoClient,
        runtime: KeyRuntime,
    ) -> None:
        self.entry = entry
        self.client = client
        self.runtime = runtime
        self.place_id = int(entry.data[CONF_CITTA])
        self.place_name: str = entry.data[CONF_PLACE_NAME]
        self._daily: list[DailyForecast] = []
        self._hourly: list[HourlyForecast] = []

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{self.place_id}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    @property
    def gateway_name(self) -> str:
        """The place's name for iLMeteo; the user's label until it is known."""
        return self.entry.data.get(CONF_GATEWAY_NAME) or self.place_name

    @property
    def link(self) -> str:
        """The place's page on ilmeteo.it."""
        return place_page_url(self.gateway_name)

    async def _async_update_data(self) -> Snapshot:
        now = dt_util.now()
        runtime = self.runtime
        plan = plan_update(runtime.tracker, runtime.status, now)
        if plan.notice is not None:
            runtime.notify(plan.notice)

        start, end = request_window(now)
        succeeded = False
        for endpoint in plan.endpoints:
            try:
                if endpoint == ENDPOINT_DAILY:
                    self._daily = await self.client.async_get_daily(self.place_id, start)
                elif endpoint == ENDPOINT_HOURLY:
                    self._hourly = await self.client.async_get_hourly(
                        self.place_id, start, end
                    )
            except IlMeteoError as err:
                if not self._handle_error(err, endpoint, now):
                    break
            else:
                succeeded = True
                runtime.status.record_success()

        if succeeded:
            runtime.dismiss()
            await self._async_learn_gateway_name(now)
        runtime.schedule_save()

        if not self._daily and not self._hourly:
            raise UpdateFailed(f"No forecast downloaded yet for {self.place_name}")
        return build_snapshot(self._daily, self._hourly, now)

    def _handle_error(self, err: IlMeteoError, endpoint: str, now: datetime) -> bool:
        """Act on a failed request; return True to go on with the next endpoint."""
        runtime = self.runtime
        decision = runtime.status.record_error(err, endpoint, now)
        _LOGGER.warning(
            "iLMeteo %s request for %s failed (%s): %s",
            endpoint, self.place_name, decision.action, err,
        )
        if decision.action is Action.REAUTH:
            runtime.schedule_save()
            raise ConfigEntryAuthFailed(str(err)) from err
        if decision.action is Action.BLOCK:
            runtime.tracker.block(now)
        if decision.notice is not None:
            runtime.notify(decision.notice, str(err))
        return decision.action is Action.DROP_ENDPOINT

    async def _async_learn_gateway_name(self, now: datetime) -> None:
        """Store the gateway's name of the place once (entries migrated from 1.x).

        Costs one request in the entry's lifetime; skipped when today's
        budget is gone, retried on a later cycle.
        """
        if self.entry.data.get(CONF_GATEWAY_NAME):
            return
        if not self.runtime.tracker.can_request(now):
            return
        try:
            place = await self.client.async_get_place(self.place_id)
        except IlMeteoError as err:
            _LOGGER.debug("Could not read the name of place %s: %s", self.place_id, err)
            return
        if place is not None and place.name:
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_GATEWAY_NAME: place.name}
            )

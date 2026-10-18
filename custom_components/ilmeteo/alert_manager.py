"""Alert evaluation, dedup/persistence, and batched Home Assistant notification dispatch."""
from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .alerts import (
    AlertProvider,
    DpcSensorAlertProvider,
    DpcVigilanceProvider,
    HeuristicAlertProvider,
    WeatherAlert,
)
from .const import DOMAIN, EVENT_WEATHER_ALERT, ILMETEO_LOGO_URL
from .coordinator import IlMeteoCoordinator

_LOGGER = logging.getLogger(__name__)

_STORAGE_VERSION = 1

_DAY_LABELS = {"today": "oggi", "tomorrow": "domani", "aftertomorrow": "dopodomani"}
_DAY_ORDER = ("today", "tomorrow", "aftertomorrow")


class IlMeteoAlertManager:
    """Watches a coordinator's data, detects alerts, notifies on change.

    Dedup is signature-based (alert_id + severity) and persisted across
    restarts. Notifications are BATCHED PER DAY: all active alerts for the
    same day are rendered into a single persistent_notification (and a single
    mobile push), re-created whenever the set of alerts for that day changes,
    and dismissed when no alerts remain for that day.

    link is the place's page on ilmeteo.it (const.place_page_url): every
    notification carries it, as iLMeteo asked when authorizing the
    integration.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: IlMeteoCoordinator,
        entry_id: str,
        citta: str,
        place_name: str,
        link: str,
        dpc_entity_id: str | None = None,
        dpc_vigilance_entity_id: str | None = None,
        notify_targets: list[str] | None = None,
    ) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.entry_id = entry_id
        self.citta = citta
        self.place_name = place_name
        self.link = link
        self.notify_targets = notify_targets or []
        # Add future providers here (official iLMeteo feed, if/when offered).
        self.providers: list[AlertProvider] = [HeuristicAlertProvider()]
        if dpc_entity_id:
            self.providers.append(DpcSensorAlertProvider(hass, dpc_entity_id))
        if dpc_vigilance_entity_id:
            self.providers.append(DpcVigilanceProvider(hass, dpc_vigilance_entity_id))

        self._store: Store[dict[str, str]] = Store(
            hass, _STORAGE_VERSION, f"{DOMAIN}_{entry_id}_alerts"
        )
        self._active: dict[str, str] = {}  # alert_id -> signature
        self._unsub: callable | None = None

    async def async_start(self) -> None:
        """Load persisted state, subscribe to the coordinator, evaluate once."""
        self._active = await self._store.async_load() or {}
        self._unsub = self.coordinator.async_add_listener(self._handle_update)
        await self._evaluate()

    def async_stop(self) -> None:
        """Unsubscribe from the coordinator. Does not clear persisted state."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def _handle_update(self) -> None:
        self.hass.async_create_task(self._evaluate())

    async def _evaluate(self) -> None:
        data = self.coordinator.data
        alerts: list[WeatherAlert] = []
        for provider in self.providers:
            try:
                alerts += await provider.async_get_alerts(
                    data, self.citta, self.place_name,
                    active_alert_ids=frozenset(self._active),
                )
            except Exception:
                _LOGGER.exception(
                    "Alert provider %s failed for %s", provider.name, self.place_name
                )

        current = {alert.alert_id: alert for alert in alerts}
        link = self.link

        # Determine which days changed (new alert, severity change, or cleared)
        changed_days: set[str] = set()

        for alert_id, alert in current.items():
            if self._active.get(alert_id) != alert.signature:
                changed_days.add(alert.day)
                self._active[alert_id] = alert.signature
                self.hass.bus.async_fire(
                    EVENT_WEATHER_ALERT,
                    {
                        "entry_id": self.entry_id,
                        "place_name": self.place_name,
                        "alert_id": alert.alert_id,
                        "severity": alert.severity,
                        "kind": alert.kind,
                        "title": alert.title,
                        "message": alert.message,
                        "source": alert.source,
                        "day": alert.day,
                        "link": link,
                        "cleared": False,
                    },
                )

        for alert_id in list(self._active):
            if alert_id not in current:
                # We no longer know the day of a cleared alert from the store —
                # refresh all day notifications to be safe.
                changed_days.update(_DAY_ORDER)
                del self._active[alert_id]
                self.hass.bus.async_fire(
                    EVENT_WEATHER_ALERT,
                    {
                        "entry_id": self.entry_id,
                        "place_name": self.place_name,
                        "alert_id": alert_id,
                        "cleared": True,
                    },
                )

        # Re-render one batched notification per changed day
        alerts_by_day: dict[str, list[WeatherAlert]] = {}
        for alert in current.values():
            alerts_by_day.setdefault(alert.day, []).append(alert)

        for day in changed_days:
            day_alerts = alerts_by_day.get(day, [])
            if day_alerts:
                await self._notify_day(day, day_alerts, link)
            else:
                await self._dismiss_day(day)

        await self._store.async_save(self._active)

    def _notification_id(self, day: str) -> str:
        return f"{DOMAIN}_{self.entry_id}_{day}"

    async def _notify_day(
        self, day: str, day_alerts: list[WeatherAlert], link: str
    ) -> None:
        """Create/refresh the single batched notification for a day."""
        day_label = _DAY_LABELS.get(day, day)
        count = len(day_alerts)

        if count == 1:
            title = f"⚠️ {self.place_name}: {day_alerts[0].title}"
        else:
            title = f"⚠️ {self.place_name}: {count} allerte meteo ({day_label})"

        # Panel: table layout with logo, one bullet per alert, single link
        items_html = "<br>".join(f"• {a.message}" for a in day_alerts)
        panel_message = (
            f"<table><tr>"
            f"<td><img src='{ILMETEO_LOGO_URL}' width='72'></td>"
            f"<td>&nbsp;&nbsp;</td>"
            f"<td>{items_html}<br><br>"
            f"🔗 <a href='{link}'>Dettagli e previsioni complete su iLMeteo.it</a></td>"
            f"</tr></table>"
        )
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "notification_id": self._notification_id(day),
                "title": title,
                "message": panel_message,
            },
            blocking=False,
        )

        # Mobile push: plain-text bullet list, iLMeteo link as URI action button
        push_message = "\n".join(f"• {a.message}" for a in day_alerts)
        for target in self.notify_targets:
            self.hass.async_create_task(
                self._push_with_retry(target, title, push_message, link)
            )

    async def _dismiss_day(self, day: str) -> None:
        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": self._notification_id(day)},
            blocking=False,
        )

    async def _push_with_retry(
        self, target: str, title: str, message: str, link: str, attempt: int = 0
    ) -> None:
        """Push to a notify.mobile_app_* target, retrying if not yet registered.

        The companion app service registers a few seconds after HA setup —
        retrying up to 5 times (10s apart) covers the typical boot window.
        """
        domain, service = target.split(".", 1)
        if not self.hass.services.has_service(domain, service):
            if attempt < 5:
                delay = 10 * (attempt + 1)
                _LOGGER.debug(
                    "Notify target %s not yet available, retrying in %ds (attempt %d/5)",
                    target, delay, attempt + 1,
                )
                async def _retry(_attempt=attempt):
                    await self._push_with_retry(target, title, message, link, _attempt + 1)
                self.hass.loop.call_later(
                    delay, lambda: self.hass.async_create_task(_retry())
                )
            else:
                _LOGGER.warning(
                    "Notify target %s not available after 5 attempts, giving up", target
                )
            return
        try:
            await self.hass.services.async_call(
                domain,
                service,
                {
                    "title": title,
                    "message": message,
                    "data": {
                        "image": ILMETEO_LOGO_URL,
                        "actions": [
                            {"action": "URI", "title": "Apri iLMeteo.it", "uri": link}
                        ],
                    },
                },
                blocking=False,
            )
        except Exception:
            _LOGGER.exception("Push to %s failed", target)

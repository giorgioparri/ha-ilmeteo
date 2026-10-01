"""DataUpdateCoordinator for iLMeteo.it (box scraper)."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, TypeVar

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import IlMeteoError, IlMeteoParseError, IlMeteoScraper
from .const import DEFAULT_NUM_DAYS, DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")

BOX_TYPES = ("real1", "day1", "tri1")


def issue_id_for(citta: str, box_type: str) -> str:
    """Repair issue_id for a given location + box type."""
    return f"box_parse_error_{citta}_{box_type}"


class IlMeteoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches current/daily/hourly data from the real1/day1/tri1 boxes."""

    def __init__(
        self,
        hass: HomeAssistant,
        scraper: IlMeteoScraper,
        citta: str,
        place_name: str,
    ) -> None:
        self.scraper = scraper
        self.citta = citta
        self.place_name = place_name
        self._last_good: dict[str, Any] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{citta}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all three boxes independently."""
        current = await self._fetch_box("real1", self.scraper.fetch_current, default={})
        daily = await self._fetch_box(
            "day1",
            lambda: self.scraper.fetch_daily_summary(DEFAULT_NUM_DAYS),
            default=[],
        )
        days = await self._fetch_box(
            "tri1",
            lambda: self.scraper.fetch_forecast(DEFAULT_NUM_DAYS),
            default=[],
        )

        if not current and not daily and not days:
            raise UpdateFailed(
                f"All iLMeteo box fetches failed for {self.place_name}"
            )

        _LOGGER.debug(
            "Fetched data for %s: current=%s, %s daily summaries, %s hourly days",
            self.place_name,
            current,
            len(daily),
            len(days),
        )
        return {"current": current, "daily": daily, "days": days}

    async def _fetch_box(
        self,
        box_type: str,
        fetch_fn: Callable[[], Awaitable[T]],
        default: T,
    ) -> T:
        """Fetch one box; on failure raise/clear a Repair and fall back."""
        issue_id = issue_id_for(self.citta, box_type)
        try:
            result = await fetch_fn()
        except IlMeteoParseError as err:
            _LOGGER.warning(
                "Parse error on the %s box for %s: %s", box_type, self.place_name, err
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="box_parse_error",
                translation_placeholders={
                    "place_name": self.place_name,
                    "box_type": box_type,
                },
                learn_more_url="https://github.com/giorgioparri/ha-ilmeteo/issues",
            )
            return self._last_good.get(box_type, default)
        except IlMeteoError as err:
            _LOGGER.debug(
                "Fetch error on the %s box for %s: %s", box_type, self.place_name, err
            )
            return self._last_good.get(box_type, default)
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            self._last_good[box_type] = result
            return result

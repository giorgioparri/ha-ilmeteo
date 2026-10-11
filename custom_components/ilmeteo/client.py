"""Client for the iLMeteo.it API Gateway (apigateway.ilmeteo.it/v1).

No Home Assistant dependency: only aiohttp. Parsing functions are pure and
work on the decoded JSON, so they can be tested on saved responses.

Authentication: the key travels as-is in the Authorization header. The
gateway rejects "Bearer <key>" with 401, so normalize_key() strips the prefix
from whatever the user pasted.

Errors: every authentication failure arrives as 401 and is told apart only by
body.message (and errorCode for OUT_OF_SCOPE). classify_error() turns status
and body into one exception type per behaviour the caller must adopt:

    IlMeteoAuthError              key invalid/expired/disabled -> reauth
    IlMeteoQuotaExceeded          daily limit reached -> stop until midnight
    IlMeteoOutOfScope             endpoint not covered by the key -> never again
    IlMeteoUnrecognizedAuthError  401 with an unknown message -> temporary
    IlMeteoConnectionError        network, timeout, 5xx, garbled body -> temporary
    IlMeteoRequestError           other 4xx -> a bug on our side
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import aiohttp

BASE_URL = "https://apigateway.ilmeteo.it/v1"
MODEL_COMPOSITE = "COMPOSITE"
REQUEST_TIMEOUT = 30  # seconds
NEARBY_RADIUS_KM = 15  # the gateway default is a few km; too narrow for a choice
SEARCH_COUNTRY = "IT"
PRECIPITATION_TYPE_SNOW = 12

_BEARER_RE = re.compile(r"^\s*bearer\s+", re.IGNORECASE)

# body.message fragments, lowercased. Matched as substrings so a trailing
# full stop or a capitalisation change does not turn a known case unknown.
_AUTH_REASONS = (
    ("token errato", "invalid"),
    ("token scaduto", "expired"),
    ("credenziali disattivate", "disabled"),
)
_QUOTA_TRIGGERED = "limite di richieste giornaliero"
_QUOTA_BLOCKED = "temporaneamente bloccato"
_OUT_OF_SCOPE = "OUT_OF_SCOPE"


# --- Exceptions ------------------------------------------------------------

class IlMeteoError(Exception):
    """Base class for every error raised by this module."""


class IlMeteoConnectionError(IlMeteoError):
    """Gateway unreachable or answering garbage: retry on the next cycle."""


class IlMeteoRequestError(IlMeteoError):
    """The gateway refused the request itself (4xx other than 401)."""


class IlMeteoAuthError(IlMeteoError):
    """The key is definitively unusable: invalid, expired or disabled."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class IlMeteoQuotaExceeded(IlMeteoError):
    """Daily request limit reached; the key is blocked until midnight (Rome).

    triggered is True for the request that crossed the limit and False for
    the ones sent afterwards to an already blocked key.
    """

    def __init__(self, message: str, *, triggered: bool) -> None:
        super().__init__(message)
        self.triggered = triggered


class IlMeteoOutOfScope(IlMeteoError):
    """The key does not cover this endpoint."""


class IlMeteoUnrecognizedAuthError(IlMeteoError):
    """401 with a message we do not know: treated as temporary."""


def classify_error(status: int, body: str) -> IlMeteoError:
    """Map an HTTP error status and raw body to the matching exception."""
    message = ""
    error_code = None
    try:
        payload = json.loads(body) if body else None
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = str(payload.get("message") or "")
        error_code = payload.get("errorCode")

    if status == 401:
        if error_code == _OUT_OF_SCOPE:
            return IlMeteoOutOfScope(message or _OUT_OF_SCOPE)
        lowered = message.strip().lower()
        for fragment, reason in _AUTH_REASONS:
            if fragment in lowered:
                return IlMeteoAuthError(reason, message)
        if _QUOTA_TRIGGERED in lowered:
            return IlMeteoQuotaExceeded(message, triggered=True)
        if _QUOTA_BLOCKED in lowered:
            return IlMeteoQuotaExceeded(message, triggered=False)
        return IlMeteoUnrecognizedAuthError(message or "HTTP 401")
    if status >= 500:
        return IlMeteoConnectionError(f"HTTP {status}")
    return IlMeteoRequestError(f"HTTP {status}: {message}".rstrip(": "))


def normalize_key(raw: str) -> str:
    """Strip whitespace and an optional 'Bearer ' prefix from a pasted key."""
    return _BEARER_RE.sub("", raw).strip()


# --- Data model ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Region:
    """An Italian region, e.g. id 'TOS', name 'Toscana'."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class Province:
    """An Italian province, e.g. id 'SI', name 'Siena', region 'TOS'."""

    id: str
    name: str
    region: str | None


@dataclass(frozen=True, slots=True)
class Place:
    """A location known to the gateway.

    real_id is the place whose forecast the gateway actually serves: for many
    hamlets and city districts it is the comune (Roma Testaccio -> Roma).
    istat_code is the comune's code, shared by its hamlets: not a key.
    """

    id: int
    real_id: int
    name: str
    province: str | None
    region: str | None
    istat_code: str | None
    latitude: float | None
    longitude: float | None
    timezone: str | None

    @property
    def is_alias(self) -> bool:
        """True when the forecast is borrowed from another place."""
        return self.real_id != self.id


@dataclass(frozen=True, slots=True)
class DailyForecast:
    """One day of the COMPOSITE daily forecast.

    Speeds in m/s, precipitation in mm, pressure in hPa, freezing level in m.
    timeDetails.lightTime is deliberately not exposed: on daily data it only
    reflects the hour of the request, not the day.
    """

    date: date
    outlook: int | None
    temperature_max: float | None
    temperature_min: float | None
    precipitation: float | None
    precipitation_probability: float | None
    wind_speed: float | None
    wind_gust: float | None
    wind_bearing: float | None
    pressure: float | None
    reliability: float | None
    freezing_level: float | None


@dataclass(frozen=True, slots=True)
class HourlyForecast:
    """One hourly slot. time is timezone-aware, start of the hour.

    Speeds in m/s, visibility in m, pressure in hPa. The gateway reports
    precipitation in mm for rain and in cm for snow (glossary): a snow slot
    therefore has precipitation None and the amount in snowfall, in cm.
    pv_production is the gateway's uvDetails.kWhProduction, whose unit and
    reference system are still to be confirmed by iLMeteo.
    """

    time: datetime
    outlook: int | None
    is_night: bool
    temperature: float | None
    apparent_temperature: float | None
    humidity: float | None
    pressure: float | None
    visibility: float | None
    uv_index: float | None
    wind_speed: float | None
    wind_gust: float | None
    wind_bearing: float | None
    precipitation: float | None
    snowfall: float | None
    freezing_level: float | None
    pv_production: float | None


# --- Parsing ---------------------------------------------------------------

def _forecast_rows(payload: Any) -> list[dict[str, Any]]:
    """Return the forecasts list from [{placeId, forecasts: [...]}] or {}."""
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not isinstance(payload, dict):
        return []
    rows = payload.get("forecasts")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None else None


def parse_place(payload: Any) -> Place | None:
    """Parse /geography/places/{id}; None when the gateway returns {}."""
    if not isinstance(payload, dict):
        return None
    place_id = _int(payload.get("id"))
    if place_id is None:
        return None
    real_id = _int(payload.get("realId"))
    return Place(
        id=place_id,
        real_id=real_id if real_id is not None else place_id,
        name=str(payload.get("name") or ""),
        province=payload.get("province"),
        region=payload.get("region"),
        istat_code=payload.get("istatCode"),
        latitude=_num(payload.get("latitude")),
        longitude=_num(payload.get("longitude")),
        timezone=payload.get("timezone"),
    )


def parse_places(payload: Any) -> list[Place]:
    """Parse a list of places (cascade, search, coordinates)."""
    if not isinstance(payload, list):
        return []
    return [p for p in map(parse_place, payload) if p is not None]


def parse_regions(payload: Any) -> list[Region]:
    """Parse /geography/regions."""
    if not isinstance(payload, list):
        return []
    return [
        Region(id=str(r["id"]), name=str(r.get("name") or r["id"]))
        for r in payload
        if isinstance(r, dict) and r.get("id")
    ]


def parse_provinces(payload: Any) -> list[Province]:
    """Parse /geography/regions/{region}/provinces."""
    if not isinstance(payload, list):
        return []
    return [
        Province(
            id=str(p["id"]),
            name=str(p.get("name") or p["id"]),
            region=p.get("region"),
        )
        for p in payload
        if isinstance(p, dict) and p.get("id")
    ]


def parse_daily(payload: Any) -> list[DailyForecast]:
    """Parse /forecasts/{date}/daily/{model}/places/{id}."""
    days: list[DailyForecast] = []
    for row in _forecast_rows(payload):
        try:
            day = date.fromisoformat(str(row["forecastTs"])[:10])
        except (KeyError, ValueError):
            continue
        days.append(
            DailyForecast(
                date=day,
                outlook=_int(row.get("outlook")),
                temperature_max=_num(row.get("maxTemperature")),
                temperature_min=_num(row.get("minTemperature")),
                precipitation=_num(row.get("precipitationInMm")),
                precipitation_probability=_num(row.get("precipitationProbability")),
                wind_speed=_num(row.get("windSpeed")),
                wind_gust=_num(row.get("windMaxSpeed")),
                wind_bearing=_num(row.get("windDirection")),
                pressure=_num(row.get("pressure")),
                reliability=_num(row.get("reliability")),
                freezing_level=_num(row.get("freezingLevel")),
            )
        )
    return days


def parse_hourly(payload: Any) -> list[HourlyForecast]:
    """Parse /forecasts/{from}/{to}/hourly/{model}/places/{id}."""
    slots: list[HourlyForecast] = []
    for row in _forecast_rows(payload):
        try:
            time = datetime.fromisoformat(str(row["forecastTs"]))
        except (KeyError, ValueError):
            continue
        if time.tzinfo is None:
            continue
        temp_details = row.get("temperatureDetails") or {}
        time_details = row.get("timeDetails") or {}
        uv_details = row.get("uvDetails") or {}
        precip_details = row.get("precipitationDetails") or {}
        amount = _num(row.get("precipitation"))
        is_snow = (
            row.get("precipitationType") == PRECIPITATION_TYPE_SNOW
            or precip_details.get("isSnow") is True
        )
        slots.append(
            HourlyForecast(
                time=time,
                outlook=_int(row.get("outlook")),
                is_night=time_details.get("lightTime") == "NIGHT",
                temperature=_num(row.get("temperature")),
                apparent_temperature=_num(temp_details.get("apparentTemperature")),
                humidity=_num(row.get("humidity")),
                pressure=_num(row.get("pressure")),
                visibility=_num(row.get("visibility")),
                uv_index=_num(row.get("uv")),
                wind_speed=_num(row.get("windSpeed")),
                wind_gust=_num(row.get("windMaxSpeed")),
                wind_bearing=_num(row.get("windDirection")),
                precipitation=None if is_snow else amount,
                snowfall=amount if is_snow else None,
                freezing_level=_num(row.get("freezingLevel")),
                pv_production=_num(uv_details.get("kWhProduction")),
            )
        )
    return slots


def current_slot(
    slots: list[HourlyForecast], now: datetime
) -> HourlyForecast | None:
    """Return the slot whose hour contains now, or None if out of range.

    Stands in for /forecasts/realtime, which currently answers {}.
    """
    for slot in slots:
        if slot.time <= now < slot.time + timedelta(hours=1):
            return slot
    return None


# --- Client ----------------------------------------------------------------

class IlMeteoClient:
    """Thin async wrapper around the gateway endpoints the integration uses.

    on_request, if given, is called once for every request actually sent:
    the gateway charges rejected requests against the quota as well.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        on_request: Callable[[], None] | None = None,
    ) -> None:
        self._session = session
        self._api_key = normalize_key(api_key)
        self._base_url = base_url.rstrip("/")
        self._on_request = on_request

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self._base_url}/{path.lstrip('/')}"
        query = {"format": "json", **(params or {})}
        if self._on_request is not None:
            self._on_request()
        try:
            async with self._session.get(
                url,
                params=query,
                headers={"Authorization": self._api_key},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                body = await response.text()
                status = response.status
        except (aiohttp.ClientError, TimeoutError) as err:
            raise IlMeteoConnectionError(str(err) or type(err).__name__) from err

        if status != 200:
            raise classify_error(status, body)
        try:
            return json.loads(body) if body else {}
        except ValueError as err:
            raise IlMeteoConnectionError("Invalid JSON in response") from err

    async def async_get_place(self, place_id: int) -> Place | None:
        """Fetch a place's master data; None if the gateway does not know it."""
        return parse_place(await self._get(f"geography/places/{int(place_id)}"))

    async def async_get_daily(
        self, place_id: int, start: date, model: str = MODEL_COMPOSITE
    ) -> list[DailyForecast]:
        """Fetch the daily forecast starting at start (8 days for COMPOSITE)."""
        path = f"forecasts/{start.isoformat()}/daily/{model}/places/{int(place_id)}"
        return parse_daily(await self._get(path))

    async def async_get_hourly(
        self,
        place_id: int,
        start: date,
        end: date,
        model: str = MODEL_COMPOSITE,
    ) -> list[HourlyForecast]:
        """Fetch hourly slots from 00:00 of start to the last slot of end."""
        path = (
            f"forecasts/{start.isoformat()}/{end.isoformat()}"
            f"/hourly/{model}/places/{int(place_id)}"
        )
        return parse_hourly(await self._get(path))

    async def async_get_regions(self) -> list[Region]:
        """List the Italian regions."""
        return parse_regions(await self._get("geography/regions"))

    async def async_get_provinces(self, region: str) -> list[Province]:
        """List the provinces of a region (id as returned by the gateway)."""
        path = f"geography/regions/{quote(region, safe='')}/provinces"
        return parse_provinces(await self._get(path))

    async def async_get_places(self, region: str, province: str) -> list[Place]:
        """List the places of a province, hamlets and districts included."""
        path = (
            f"geography/regions/{quote(region, safe='')}"
            f"/provinces/{quote(province, safe='')}/places"
        )
        return parse_places(await self._get(path))

    async def async_search(self, query: str, limit: int = 10) -> list[Place]:
        """Search places by name, in Italy."""
        path = f"geography/places/search/{quote(query.strip(), safe='')}"
        params = {"country": SEARCH_COUNTRY, "limit": limit}
        return parse_places(await self._get(path, params))

    async def async_nearby(
        self,
        latitude: float,
        longitude: float,
        distance_km: int = NEARBY_RADIUS_KM,
        limit: int = 10,
    ) -> list[Place]:
        """Places around a point, nearest first."""
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "distanceInKm": distance_km,
            "limit": limit,
        }
        return parse_places(await self._get("geography/places/coordinates", params))

"""Unit tests for the iLMeteo API Gateway client (client.py).

Run with:  python tests/test_api.py
No Home Assistant dependency: client.py only needs aiohttp. Parsing is tested on
real gateway responses saved in tests/fixtures/api_*.json; the HTTP layer is
tested against a local aiohttp server that plays the gateway's part, so no
request ever leaves the machine and no quota is spent.
"""
import asyncio
import contextlib
import copy
import json
import os
import sys
from datetime import UTC, date, datetime, timedelta, timezone

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "ilmeteo")
)

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from client import (
    IlMeteoAuthError,
    IlMeteoClient,
    IlMeteoConnectionError,
    IlMeteoOutOfScope,
    IlMeteoQuotaExceeded,
    IlMeteoRequestError,
    IlMeteoUnrecognizedAuthError,
    classify_error,
    current_slot,
    normalize_key,
    parse_daily,
    parse_hourly,
    parse_place,
    parse_places,
    parse_provinces,
    parse_regions,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
ROME = timezone(timedelta(hours=2))  # CEST, the offset carried by the fixtures

# The five 401 bodies documented in writing by iLMeteo.
MSG_INVALID = "Authorization Bearer Token errato"
MSG_EXPIRED = "Authorization Bearer Token scaduto"
MSG_DISABLED = "Credenziali disattivate"
MSG_LIMIT_HIT = "Limite di richieste giornaliero superato"
MSG_BLOCKED = "Accesso temporaneamente bloccato"


def _fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def _body(message, **extra):
    return json.dumps({"message": message, **extra})


# --- API key -------------------------------------------------------------

def test_normalize_key_plain():
    assert normalize_key("abc123") == "abc123"


def test_normalize_key_strips_whitespace_and_bearer():
    # The gateway rejects "Bearer <key>" with 401: users pasting the prefix
    # from the docs must not end up with a key that looks invalid.
    assert normalize_key("  Bearer abc123\n") == "abc123"
    assert normalize_key("bearer abc123") == "abc123"
    assert normalize_key("BEARER   abc123") == "abc123"


# --- Error classification ------------------------------------------------

def test_401_invalid_expired_disabled_are_definitive():
    for message, reason in (
        (MSG_INVALID, "invalid"),
        (MSG_EXPIRED, "expired"),
        (MSG_DISABLED, "disabled"),
    ):
        err = classify_error(401, _body(message))
        assert isinstance(err, IlMeteoAuthError), message
        assert err.reason == reason


def test_401_quota_messages():
    hit = classify_error(401, _body(MSG_LIMIT_HIT))
    blocked = classify_error(401, _body(MSG_BLOCKED))
    assert isinstance(hit, IlMeteoQuotaExceeded)
    assert isinstance(blocked, IlMeteoQuotaExceeded)
    # The first marks the request that crossed the limit, the second every
    # request after it. Both mean the same thing for us: stop until midnight.
    assert hit.triggered is True
    assert blocked.triggered is False


def test_401_out_of_scope_keys_on_error_code_not_message():
    err = classify_error(401, _body("anything at all", errorCode="OUT_OF_SCOPE"))
    assert isinstance(err, IlMeteoOutOfScope)


def test_401_unknown_message_is_not_a_credential_failure():
    # If iLMeteo rewords a message, a valid key must not be thrown away.
    err = classify_error(401, _body("Token non valido per qualche motivo nuovo"))
    assert isinstance(err, IlMeteoUnrecognizedAuthError)
    assert not isinstance(err, IlMeteoAuthError)


def test_401_without_json_body_is_unrecognized():
    assert isinstance(classify_error(401, "<html>Unauthorized</html>"), IlMeteoUnrecognizedAuthError)
    assert isinstance(classify_error(401, ""), IlMeteoUnrecognizedAuthError)


def test_server_errors_are_temporary():
    for status in (500, 502, 503, 504):
        assert isinstance(classify_error(status, ""), IlMeteoConnectionError), status


def test_400_is_a_request_error():
    assert isinstance(classify_error(400, _body("Bad request")), IlMeteoRequestError)


# --- Places --------------------------------------------------------------

def test_parse_place_rapolano():
    place = parse_place(_fixture("api_place_5658.json"))
    assert place.id == 5658
    assert place.name == "Rapolano Terme"
    assert place.province == "SI"
    assert place.region == "TOS"
    assert place.istat_code == "052026"
    assert place.timezone == "Europe/Rome"
    assert abs(place.latitude - 43.2865) < 1e-9
    assert abs(place.longitude - 11.6042) < 1e-9


def test_parse_place_suppressed_comuni_and_hamlet_still_resolve():
    # IDs from the 1.x bundled dataset, including comuni merged away years
    # ago and a hamlet: the gateway still knows them all, which is what lets
    # existing config entries migrate without a new location choice.
    expected = {
        4074: ("Milano", "015146"),
        8: ("Abetone", "047001"),
        6235: ("San Giovanni d'Asso", "052029"),
        8500: ("Rena Majore", None),
    }
    for place_id, (name, istat) in expected.items():
        place = parse_place(_fixture(f"api_place_{place_id}.json"))
        assert place.id == place_id
        assert place.name == name
        assert place.istat_code == istat


def test_parse_place_empty_body_is_none():
    # The gateway answers 200 with {} when it has nothing (see realtime).
    assert parse_place({}) is None
    assert parse_place(None) is None


# --- Daily forecast ------------------------------------------------------

def test_parse_daily_eight_days():
    days = parse_daily(_fixture("api_daily_5658.json"))
    assert len(days) == 8
    assert [d.date for d in days] == [date(2026, 10, 8) + timedelta(days=i) for i in range(8)]


def test_parse_daily_first_day_values():
    day = parse_daily(_fixture("api_daily_5658.json"))[0]
    assert day.outlook == 8
    assert day.temperature_max == 22.22
    assert day.temperature_min == 17.46
    assert day.precipitation == 0
    assert day.precipitation_probability == 86.66
    assert day.wind_speed == 2.04
    assert day.wind_gust == 5.6
    assert day.wind_bearing == 140
    assert day.pressure == 1013
    assert day.reliability == 86.66
    assert day.freezing_level == 3416


def test_parse_daily_keeps_missing_reliability_as_none():
    assert parse_daily(_fixture("api_daily_5658.json"))[7].reliability is None


def test_parse_daily_empty():
    assert parse_daily({}) == []
    assert parse_daily([]) == []
    assert parse_daily([{"placeId": 5658, "forecasts": []}]) == []


# --- Hourly forecast -----------------------------------------------------

def test_parse_hourly_seventy_one_aware_slots():
    slots = parse_hourly(_fixture("api_hourly_5658.json"))
    assert len(slots) == 71
    assert slots[0].time == datetime(2026, 10, 8, 0, 0, tzinfo=ROME)
    assert slots[-1].time == datetime(2026, 10, 10, 22, 0, tzinfo=ROME)
    assert all(s.time.tzinfo is not None for s in slots)


def test_parse_hourly_slot_values():
    slot = parse_hourly(_fixture("api_hourly_5658.json"))[21]  # 21:00, 8 Oct
    assert slot.time == datetime(2026, 10, 8, 21, 0, tzinfo=ROME)
    assert slot.outlook == 10
    assert slot.is_night is True
    assert slot.temperature == 17.91
    assert abs(slot.apparent_temperature - 18.9896) < 1e-3
    assert slot.humidity == 93
    assert slot.pressure == 1014
    assert slot.visibility == 28779
    assert slot.uv_index == 0
    assert slot.wind_speed == 1.72
    assert slot.wind_gust == 4.8
    assert slot.wind_bearing == 157
    assert slot.precipitation == 1.66
    assert slot.freezing_level == 3293


def test_parse_hourly_day_slot_and_pv_estimate():
    slot = parse_hourly(_fixture("api_hourly_5658.json"))[12]  # 12:00, 8 Oct
    assert slot.is_night is False
    assert slot.uv_index == 0.99
    assert slot.pv_production == 330.13


def test_parse_hourly_null_wind_direction_survives():
    slots = parse_hourly(_fixture("api_hourly_5658.json"))
    calm = [s for s in slots if s.wind_bearing is None]
    assert [s.time.hour for s in calm] == [1, 2, 23, 0]


# --- Current slot --------------------------------------------------------

def test_current_slot_picks_the_hour_containing_now():
    slots = parse_hourly(_fixture("api_hourly_5658.json"))
    slot = current_slot(slots, datetime(2026, 10, 8, 21, 42, tzinfo=ROME))
    assert slot.time == datetime(2026, 10, 8, 21, 0, tzinfo=ROME)


def test_current_slot_is_timezone_independent():
    slots = parse_hourly(_fixture("api_hourly_5658.json"))
    utc_now = datetime(2026, 10, 8, 19, 42, tzinfo=UTC)  # same instant
    assert current_slot(slots, utc_now).time == datetime(2026, 10, 8, 21, 0, tzinfo=ROME)


def test_current_slot_on_exact_hour_boundary():
    slots = parse_hourly(_fixture("api_hourly_5658.json"))
    slot = current_slot(slots, datetime(2026, 10, 9, 7, 0, tzinfo=ROME))
    assert slot.time == datetime(2026, 10, 9, 7, 0, tzinfo=ROME)


def test_current_slot_outside_range_is_none():
    slots = parse_hourly(_fixture("api_hourly_5658.json"))
    assert current_slot(slots, datetime(2026, 10, 7, 23, 59, tzinfo=ROME)) is None
    assert current_slot(slots, datetime(2026, 10, 10, 23, 30, tzinfo=ROME)) is None
    assert current_slot([], datetime(2026, 10, 8, 21, 42, tzinfo=ROME)) is None


# --- Geography -----------------------------------------------------------

def test_parse_regions():
    regions = parse_regions(_fixture("api_regions.json"))
    assert len(regions) == 20
    assert regions[0].id == "ABR"
    assert regions[0].name == "Abruzzo"
    assert {r.id for r in regions} >= {"LAZ", "LOM", "TOS"}


def test_parse_provinces():
    provinces = parse_provinces(_fixture("api_provinces_tos.json"))
    assert len(provinces) == 10
    siena = next(p for p in provinces if p.id == "SI")
    assert siena.name == "Siena"
    assert siena.region == "TOS"


def test_parse_places_of_a_province_includes_hamlets():
    places = parse_places(_fixture("api_places_tos_si.json"))
    assert len(places) == 53
    names = {p.name for p in places}
    assert {"Rapolano Terme", "Siena", "Bagno Vignoni", "Crete Senesi"} <= names


def test_real_id_marks_places_that_borrow_another_forecast():
    # realId is the place whose forecast is actually served: Roma Testaccio
    # returns exactly Roma's daily forecast (checked field by field).
    testaccio = parse_places(_fixture("api_search_testaccio.json"))[0]
    assert testaccio.id == 8948
    assert testaccio.real_id == 5913
    assert testaccio.is_alias is True
    monte_sacro_alto = next(
        p for p in parse_places(_fixture("api_search_monte_sacro.json"))
        if p.name == "Roma Monte Sacro Alto"
    )
    assert monte_sacro_alto.real_id == 8872
    assert monte_sacro_alto.is_alias is False


def test_real_id_defaults_to_id_when_missing():
    data = dict(_fixture("api_place_5658.json"))
    del data["realId"]
    place = parse_place(data)
    assert place.real_id == 5658
    assert place.is_alias is False


def test_istat_code_is_not_unique():
    # Hamlets carry the code of their comune: never use it as a key.
    places = parse_places(_fixture("api_places_tos_si.json"))
    by_istat = {}
    for p in places:
        if p.istat_code:
            by_istat.setdefault(p.istat_code, []).append(p.name)
    assert sorted(by_istat["052037"]) == ["Montalcino", "Torrenieri"]


def test_parse_places_skips_garbage_and_handles_empty():
    assert parse_places([]) == []
    assert parse_places({}) == []
    assert parse_places(None) == []
    mixed = [_fixture("api_place_5658.json"), {}, "x", {"name": "no id"}]
    assert [p.id for p in parse_places(mixed)] == [5658]


# --- Precipitation intensity ---------------------------------------------

def test_hourly_carries_precipitation_intensity():
    slots = parse_hourly(_fixture("api_hourly_5658.json"))
    assert slots[6].precipitation_intensity == "STRONG"  # 06:00, 3.83 mm
    assert slots[21].precipitation_intensity == "SUBSTANTIAL"
    assert slots[12].precipitation_intensity == "ABSENT"


def test_daily_carries_precipitation_intensity():
    assert parse_daily(_fixture("api_daily_5658.json"))[0].precipitation_intensity == "SCANT"


def test_missing_intensity_is_none():
    payload = copy.deepcopy(_fixture("api_hourly_5658.json"))
    del payload[0]["forecasts"][6]["precipitationDetails"]
    assert parse_hourly(payload)[6].precipitation_intensity is None


# --- Snow ----------------------------------------------------------------

def _hourly_with_snow(row_index=21, amount=2.5):
    payload = copy.deepcopy(_fixture("api_hourly_5658.json"))
    row = payload[0]["forecasts"][row_index]
    row["precipitationType"] = 12
    row["precipitationDetails"]["isSnow"] = True
    row["precipitation"] = amount
    return payload


def test_snow_is_not_reported_as_millimetres_of_rain():
    # Glossary: precipitation is in mm for rain and in cm for snow. A cm value
    # must never reach a field HA treats as mm.
    slot = parse_hourly(_hourly_with_snow())[21]
    assert slot.precipitation is None
    assert slot.snowfall == 2.5


def test_snow_detected_from_either_flag():
    payload = copy.deepcopy(_fixture("api_hourly_5658.json"))
    row = payload[0]["forecasts"][21]
    row["precipitationType"] = 12  # type only
    assert parse_hourly(payload)[21].snowfall == 1.66
    payload = copy.deepcopy(_fixture("api_hourly_5658.json"))
    payload[0]["forecasts"][21]["precipitationDetails"]["isSnow"] = True  # flag only
    assert parse_hourly(payload)[21].snowfall == 1.66


def test_rain_slots_have_no_snowfall():
    slot = parse_hourly(_fixture("api_hourly_5658.json"))[21]
    assert slot.precipitation == 1.66
    assert slot.snowfall is None


# --- HTTP client against a fake gateway ----------------------------------

class FakeGateway:
    """Local aiohttp server answering like apigateway.ilmeteo.it/v1."""

    def __init__(self):
        self.requests = []
        self.routes = {}  # path -> (status, body text)

    def add(self, path, status, body):
        self.routes[path] = (status, body if isinstance(body, str) else json.dumps(body))

    async def handler(self, request):
        self.requests.append(request)
        status, body = self.routes.get(request.path, (404, ""))
        return web.Response(status=status, text=body, content_type="application/json")

    def app(self):
        app = web.Application()
        app.router.add_route("GET", "/{tail:.*}", self.handler)
        return app


async def _with_gateway(gateway, key, scenario, on_request=None):
    async with TestServer(gateway.app()) as server, ClientSession() as session:
        client = IlMeteoClient(
            session,
            key,
            base_url=str(server.make_url("/v1")),
            on_request=on_request,
        )
        return await scenario(client)


def test_client_sends_bare_key_and_json_format():
    gw = FakeGateway()
    gw.add("/v1/geography/places/5658", 200, _fixture("api_place_5658.json"))

    async def scenario(client):
        return await client.async_get_place(5658)

    place = asyncio.run(_with_gateway(gw, " Bearer test-key ", scenario))
    assert place.name == "Rapolano Terme"
    request = gw.requests[0]
    assert request.headers["Authorization"] == "test-key"
    assert request.query["format"] == "json"


def test_client_daily_and_hourly_paths():
    gw = FakeGateway()
    gw.add("/v1/forecasts/2026-10-08/daily/COMPOSITE/places/5658", 200, _fixture("api_daily_5658.json"))
    gw.add("/v1/forecasts/2026-10-08/2026-10-10/hourly/COMPOSITE/places/5658", 200, _fixture("api_hourly_5658.json"))

    async def scenario(client):
        daily = await client.async_get_daily(5658, date(2026, 10, 8))
        hourly = await client.async_get_hourly(5658, date(2026, 10, 8), date(2026, 10, 10))
        return daily, hourly

    daily, hourly = asyncio.run(_with_gateway(gw, "k", scenario))
    assert len(daily) == 8
    assert len(hourly) == 71


def test_client_place_not_found_returns_none():
    gw = FakeGateway()
    gw.add("/v1/geography/places/999999", 200, {})

    async def scenario(client):
        return await client.async_get_place(999999)

    assert asyncio.run(_with_gateway(gw, "k", scenario)) is None


def test_client_raises_classified_errors():
    cases = [
        (_body(MSG_INVALID), IlMeteoAuthError),
        (_body(MSG_LIMIT_HIT), IlMeteoQuotaExceeded),
        (_body(MSG_BLOCKED), IlMeteoQuotaExceeded),
        (_body("x", errorCode="OUT_OF_SCOPE"), IlMeteoOutOfScope),
        (_body("Messaggio nuovo"), IlMeteoUnrecognizedAuthError),
    ]
    for body, expected in cases:
        gw = FakeGateway()
        gw.add("/v1/geography/places/5658", 401, body)

        async def scenario(client):
            try:
                await client.async_get_place(5658)
            except Exception as exc:
                return exc
            return None

        err = asyncio.run(_with_gateway(gw, "k", scenario))
        assert isinstance(err, expected), (body, err)


def test_client_200_with_non_json_body_is_temporary():
    gw = FakeGateway()
    gw.add("/v1/geography/places/5658", 200, "<html>maintenance</html>")

    async def scenario(client):
        try:
            await client.async_get_place(5658)
        except IlMeteoConnectionError:
            return True
        return False

    assert asyncio.run(_with_gateway(gw, "k", scenario)) is True


def test_client_counts_every_request_sent_including_rejected_ones():
    # Rejected requests consume quota too: the counter must see them all.
    gw = FakeGateway()
    gw.add("/v1/geography/places/5658", 200, _fixture("api_place_5658.json"))
    gw.add("/v1/geography/places/4074", 401, _body(MSG_BLOCKED))
    sent = []

    async def scenario(client):
        await client.async_get_place(5658)
        with contextlib.suppress(IlMeteoQuotaExceeded):
            await client.async_get_place(4074)

    asyncio.run(_with_gateway(gw, "k", scenario, on_request=lambda: sent.append(1)))
    assert len(sent) == 2
    assert len(gw.requests) == 2


def test_client_unreachable_host_is_connection_error():
    async def scenario():
        async with ClientSession() as session:
            # Port 9 (discard) on loopback: nothing listens there.
            client = IlMeteoClient(session, "k", base_url="http://127.0.0.1:9/v1")
            try:
                await client.async_get_place(5658)
            except IlMeteoConnectionError:
                return True
            return False

    assert asyncio.run(scenario()) is True


def test_client_geography_paths():
    gw = FakeGateway()
    gw.add("/v1/geography/regions", 200, _fixture("api_regions.json"))
    gw.add("/v1/geography/regions/TOS/provinces", 200, _fixture("api_provinces_tos.json"))
    gw.add("/v1/geography/regions/TOS/provinces/SI/places", 200, _fixture("api_places_tos_si.json"))

    async def scenario(client):
        return (
            await client.async_get_regions(),
            await client.async_get_provinces("TOS"),
            await client.async_get_places("TOS", "SI"),
        )

    regions, provinces, places = asyncio.run(_with_gateway(gw, "k", scenario))
    assert (len(regions), len(provinces), len(places)) == (20, 10, 53)


def test_client_search_encodes_the_query_and_limits_to_italy():
    gw = FakeGateway()
    gw.add("/v1/geography/places/search/monte sacro", 200, _fixture("api_search_monte_sacro.json"))

    async def scenario(client):
        return await client.async_search("monte sacro", limit=10)

    places = asyncio.run(_with_gateway(gw, "k", scenario))
    assert [p.id for p in places] == [8880, 8872]
    request = gw.requests[0]
    assert "/search/monte%20sacro" in request.raw_path
    assert request.query["country"] == "IT"
    assert request.query["limit"] == "10"


def test_client_search_slash_cannot_escape_the_path():
    gw = FakeGateway()

    async def scenario(client):
        with contextlib.suppress(IlMeteoRequestError):
            await client.async_search("a/../../regions")

    asyncio.run(_with_gateway(gw, "k", scenario))
    assert "/search/a%2F..%2F..%2Fregions" in gw.requests[0].raw_path


def test_client_nearby_passes_radius_explicitly():
    # The gateway's default radius is a few km: around Rapolano it returned
    # only Rapolano itself. 15 km brings in the neighbouring comuni.
    gw = FakeGateway()
    gw.add("/v1/geography/places/coordinates", 200, _fixture("api_nearby_5658_15km.json"))

    async def scenario(client):
        return await client.async_nearby(43.2865, 11.6042)

    places = asyncio.run(_with_gateway(gw, "k", scenario))
    assert places[0].name == "Rapolano Terme"
    assert len(places) == 10
    query = gw.requests[0].query
    assert query["latitude"] == "43.2865"
    assert query["longitude"] == "11.6042"
    assert query["distanceInKm"] == "15"
    assert query["limit"] == "10"


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    sys.exit(1 if failed else 0)

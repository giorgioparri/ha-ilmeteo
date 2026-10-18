"""Constants for the iLMeteo.it integration."""

import unicodedata
from urllib.parse import quote

DOMAIN = "ilmeteo"

DEFAULT_SCAN_INTERVAL = 1800  # seconds (30 minutes)
DEFAULT_INFO_URL = "https://www.ilmeteo.it/"
PLACE_PAGE_BASE_URL = "https://www.ilmeteo.it/meteo/"

# Bundled at custom_components/ilmeteo/brand/logo.png (256x256). Served from
# main since it's a static asset that essentially never changes — unlike the
# HACS README case, there's no "latest release tag" concern here.
ILMETEO_LOGO_URL = (
    "https://raw.githubusercontent.com/giorgioparri/ha-ilmeteo/main/"
    "custom_components/ilmeteo/brand/logo.png"
)

# Config entry data keys
CONF_API_KEY = "api_key"
CONF_CITTA = "citta"  # gateway place id, as a string (1.x scraper code, same ids)
CONF_GATEWAY_NAME = "gateway_name"  # the place's name for iLMeteo, for the page link
CONF_PLACE_NAME = "place_name"  # display name, editable from the options
CONF_SITE_NUMBER = "site_number"
CONF_UPGRADED_FROM_1X = "upgraded_from_1x"  # set by the migration, cleared at setup

# Config entry options keys
OPT_ENABLED_SENSORS = "enabled_sensors"
OPT_ALERT_NOTIFICATIONS = "alert_notifications"
OPT_DPC_ALERT_ENTITY = "dpc_alert_entity_id"
OPT_DPC_VIGILANCE_ENTITY = "dpc_vigilance_entity_id"
OPT_NOTIFY_TARGETS = "notify_targets"

DEFAULT_ALERT_NOTIFICATIONS = True

# Fired on both new/worsened and cleared alerts; see alert_manager.py
EVENT_WEATHER_ALERT = f"{DOMAIN}_weather_alert"

# Optional sensor identifiers: "current" = the hourly slot containing now,
# "today" = the first daily row. The order is the one shown in the forms.
SENSOR_TEMPERATURE = "temperature"
SENSOR_APPARENT_TEMPERATURE = "apparent_temperature"
SENSOR_DEW_POINT = "dew_point"
SENSOR_HUMIDITY = "humidity"
SENSOR_PRESSURE = "pressure"
SENSOR_VISIBILITY = "visibility"
SENSOR_UV_INDEX = "uv_index"
SENSOR_WIND_SPEED = "wind_speed"
SENSOR_WIND_GUST = "wind_gust"
SENSOR_WIND_BEARING = "wind_bearing"
SENSOR_PRECIPITATION_HOUR = "precipitation_hour"
SENSOR_FREEZING_LEVEL = "freezing_level"
SENSOR_SNOW_LEVEL = "snow_level"
SENSOR_TEMPERATURE_MIN = "temperature_min"
SENSOR_TEMPERATURE_MAX = "temperature_max"
SENSOR_PRECIPITATION_PROBABILITY = "precipitation_probability"
SENSOR_PRECIPITATION_TODAY = "precipitation_today"
SENSOR_RELIABILITY = "reliability"

ALL_OPTIONAL_SENSORS = [
    SENSOR_TEMPERATURE,
    SENSOR_APPARENT_TEMPERATURE,
    SENSOR_DEW_POINT,
    SENSOR_HUMIDITY,
    SENSOR_PRESSURE,
    SENSOR_VISIBILITY,
    SENSOR_UV_INDEX,
    SENSOR_WIND_SPEED,
    SENSOR_WIND_GUST,
    SENSOR_WIND_BEARING,
    SENSOR_PRECIPITATION_HOUR,
    SENSOR_FREEZING_LEVEL,
    SENSOR_SNOW_LEVEL,
    SENSOR_TEMPERATURE_MIN,
    SENSOR_TEMPERATURE_MAX,
    SENSOR_PRECIPITATION_PROBABILITY,
    SENSOR_PRECIPITATION_TODAY,
    SENSOR_RELIABILITY,
]

# ---------------------------------------------------------------------------
# Condition mapping for the API Gateway: outlook code -> HA condition string.
#
# The 24 codes are those of the gateway glossary (Glossary_API_Gateway_V02).
# The code is the key, not outlookDescription: the Italian wording may change,
# the documented code does not. Codes whose label the 1.x scraper already
# handled keep the condition they had there.
#
# The glossary uses the same code by day and by night; day/night comes from
# timeDetails.lightTime on hourly slots. Daily forecasts are always day.
# ---------------------------------------------------------------------------

OUTLOOK_CONDITION_MAP: dict[int, str] = {
    1: "sunny",  # sereno
    2: "sunny",  # sole e caldo
    3: "partlycloudy",  # poco nuvoloso
    4: "partlycloudy",  # nubi sparse
    5: "rainy",  # pioggia e schiarite
    6: "snowy-rainy",  # pioggia mista a neve e schiarite
    7: "snowy",  # neve e schiarite
    8: "cloudy",  # coperto
    9: "rainy",  # pioggia debole
    10: "rainy",  # pioggia
    11: "snowy",  # neve
    12: "snowy-rainy",  # pioggia mista a neve
    13: "lightning-rainy",  # temporale
    14: "fog",  # nebbia
    15: "fog",  # nebbia al mattino
    16: "lightning-rainy",  # temporale e schiarite
    17: "hail",  # grandine
    18: "snowy",  # neve debole
    19: "hail",  # temporale con grandine e schiarite
    20: "hail",  # temporale con grandine
    21: "partlycloudy",  # poco nuvoloso e caldo
    22: "sunny",  # sole e caldo
    23: "partlycloudy",  # nubi sparse e caldo
    24: "sunny",  # caldo estremo
}


# Rain codes that turn into 'pouring' when precipitationDetails.intensity is
# at least STRONG. The glossary orders intensity as ABSENT, SCANT, MODERATE,
# SUBSTANTIAL, COPIOUS, STRONG, REALLY_STRONG; observed rates put STRONG near
# 4 mm/h. Code 9 ("pioggia debole") is left out: light rain never pours.
POURING_OUTLOOKS: frozenset[int] = frozenset({5, 10})
POURING_INTENSITIES: frozenset[str] = frozenset({"STRONG", "REALLY_STRONG"})


def outlook_to_condition(
    code: int | None,
    is_night: bool = False,
    intensity: str | None = None,
) -> str | None:
    """Resolve an HA condition from a gateway outlook code.

    At night only 'sunny' changes, to 'clear-night': HA has no night variant
    for the other conditions (same rule as 1.1.4, #7). Rain with a strong
    precipitation intensity becomes 'pouring', by day and by night.
    """
    if code is None:
        return None
    condition = OUTLOOK_CONDITION_MAP.get(code)
    if code in POURING_OUTLOOKS and intensity in POURING_INTENSITIES:
        return "pouring"
    if is_night and condition == "sunny":
        return "clear-night"
    return condition


# ---------------------------------------------------------------------------
# Link to the place's page on ilmeteo.it
#
# iLMeteo authorized the integration on condition that notifications link to
# the location's page. The API Gateway does not return that URL, so it is
# built from the place name with the site's own slugify (iLMeteo, Oct 2026),
# an ICU transliterator: Any-Latin; remove nonspacing marks, punctuation and
# symbols; Latin-ASCII; lower; collapse spaces; separators -> '+'.
# Punctuation is dropped, not replaced: "Castiglione d'Orcia" becomes
# "castiglione+dorcia". Places with duplicate names may have other slugs.
# ---------------------------------------------------------------------------

# Latin-ASCII letters that NFKD does not decompose.
_LATIN_ASCII = str.maketrans({
    "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE",
    "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L",
})


def place_page_url(name: str | None) -> str:
    """Return the ilmeteo.it page of a place, or the homepage without a name."""
    if not name or not name.strip():
        return DEFAULT_INFO_URL
    decomposed = unicodedata.normalize("NFKD", name.translate(_LATIN_ASCII))
    kept = []
    for ch in decomposed:
        category = unicodedata.category(ch)
        if category[0] == "Z":
            kept.append(" ")
        elif category[0] not in "MPS" and ch.isascii():
            kept.append(ch)
    slug = "+".join("".join(kept).lower().split())
    return PLACE_PAGE_BASE_URL + quote(slug, safe="+") if slug else DEFAULT_INFO_URL

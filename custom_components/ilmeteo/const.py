"""Constants for the iLMeteo.it integration."""

DOMAIN = "ilmeteo"
PLATFORMS = ["weather", "sensor"]

DEFAULT_SCAN_INTERVAL = 1800  # seconds (30 minutes)
DEFAULT_NUM_DAYS = 6
DEFAULT_INFO_URL = "https://www.ilmeteo.it/"

# Bundled at custom_components/ilmeteo/brand/logo.png (256x256). Served from
# main since it's a static asset that essentially never changes — unlike the
# HACS README case, there's no "latest release tag" concern here.
ILMETEO_LOGO_URL = (
    "https://raw.githubusercontent.com/giorgioparri/ha-ilmeteo/main/"
    "custom_components/ilmeteo/brand/logo.png"
)

# Config entry data keys
CONF_CITTA = "citta"
CONF_PLACE_NAME = "place_name"
CONF_SITE_NUMBER = "site_number"

# Config entry options keys
OPT_ENABLED_SENSORS = "enabled_sensors"
OPT_ALERT_NOTIFICATIONS = "alert_notifications"
OPT_DPC_ALERT_ENTITY = "dpc_alert_entity_id"
OPT_DPC_VIGILANCE_ENTITY = "dpc_vigilance_entity_id"
OPT_NOTIFY_TARGETS = "notify_targets"

DEFAULT_ALERT_NOTIFICATIONS = True

# Fired on both new/worsened and cleared alerts; see alert_manager.py
EVENT_WEATHER_ALERT = f"{DOMAIN}_weather_alert"

# Optional sensor identifiers ("current" = real1, "today" = day1 row 0)
SENSOR_TEMPERATURE = "temperature"
SENSOR_HUMIDITY = "humidity"
SENSOR_WIND_SPEED = "wind_speed"
SENSOR_WIND_BEARING = "wind_bearing"
SENSOR_TEMPERATURE_MIN = "temperature_min"
SENSOR_TEMPERATURE_MAX = "temperature_max"
SENSOR_PRECIPITATION_PROBABILITY = "precipitation_probability"

ALL_OPTIONAL_SENSORS = [
    SENSOR_TEMPERATURE,
    SENSOR_HUMIDITY,
    SENSOR_WIND_SPEED,
    SENSOR_WIND_BEARING,
    SENSOR_TEMPERATURE_MIN,
    SENSOR_TEMPERATURE_MAX,
    SENSOR_PRECIPITATION_PROBABILITY,
]

# ---------------------------------------------------------------------------
# Condition mapping: sprite code (ss-smallN, >100 = night) + Italian label
# -> HA condition string. Used by the 1.x box scraper and removed with it.
# ---------------------------------------------------------------------------

# Italian label (lowercased) -> HA condition
CONDITION_TEXT_MAP = {
    "sereno": "sunny",
    "poco nuvoloso": "partlycloudy",
    "parzialmente nuvoloso": "partlycloudy",
    "nubi sparse": "partlycloudy",
    "velato": "partlycloudy",
    "poco velato": "partlycloudy",
    "nuvoloso": "cloudy",
    "molto nuvoloso": "cloudy",
    "coperto": "cloudy",
    "nebbia": "fog",
    "foschia": "fog",
    "pioggia debole": "rainy",
    "pioggia": "rainy",
    "pioggia moderata": "rainy",
    "pioviggine": "rainy",
    "pioggia forte": "pouring",
    "rovesci": "pouring",
    "rovesci di pioggia": "pouring",
    "temporale": "lightning-rainy",
    "temporali": "lightning-rainy",
    "temporale forte": "lightning-rainy",
    "neve": "snowy",
    "neve debole": "snowy",
    "nevischio": "snowy",
    "pioggia e neve": "snowy-rainy",
    "pioggia mista a neve": "snowy-rainy",
    "grandine": "hail",
    "ventoso": "windy",
}

# Fallback by numeric code, used if the text label is unknown
CONDITION_CODE_MAP = {
    1: "sunny",
    2: "partlycloudy",
    3: "partlycloudy",
    4: "cloudy",
    5: "cloudy",
    6: "fog",
    7: "rainy",
    8: "rainy",
    9: "pouring",
    10: "lightning-rainy",
    11: "snowy",
    12: "snowy-rainy",
    13: "hail",
}


def map_condition(text: str | None, code: str | None) -> str | None:
    """Resolve an HA condition from the Italian label and/or sprite code."""
    is_night = False
    base_code = None
    if code:
        digits = "".join(ch for ch in code if ch.isdigit())
        if digits:
            num = int(digits)
            if num >= 100:
                is_night = True
                num -= 100
            base_code = num

    condition = None
    if text:
        condition = CONDITION_TEXT_MAP.get(text.strip().lower())
    if condition is None and base_code is not None:
        condition = CONDITION_CODE_MAP.get(base_code)

    if is_night and condition == "sunny":
        return "clear-night"
    return condition


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

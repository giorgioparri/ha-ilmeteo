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
# -> HA condition string
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

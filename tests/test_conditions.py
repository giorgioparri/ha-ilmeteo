"""Unit tests for the API Gateway outlook -> HA condition mapping (const.py).

Run with:  python tests/test_conditions.py
No Home Assistant dependency. The outlook codes and their Italian labels come
from the gateway glossary (Glossary_API_Gateway_V02.pdf); the label is used
here only to check that codes already handled by the 1.x scraper keep the
condition they had.
"""
import json
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "ilmeteo")
)

from const import CONDITION_TEXT_MAP, OUTLOOK_CONDITION_MAP, outlook_to_condition

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# Glossary: code -> Italian label (day description).
GLOSSARY = {
    1: "sereno",
    2: "sole e caldo",
    3: "poco nuvoloso",
    4: "nubi sparse",
    5: "pioggia e schiarite",
    6: "pioggia mista a neve e schiarite",
    7: "neve e schiarite",
    8: "coperto",
    9: "pioggia debole",
    10: "pioggia",
    11: "neve",
    12: "pioggia mista a neve",
    13: "temporale",
    14: "nebbia",
    15: "nebbia al mattino",
    16: "temporale e schiarite",
    17: "grandine",
    18: "neve debole",
    19: "temporale con grandine e schiarite",
    20: "temporale con grandine",
    21: "poco nuvoloso e caldo",
    22: "sole e caldo",
    23: "nubi sparse e caldo",
    24: "caldo estremo",
}

# Expected daytime condition for every glossary code.
EXPECTED_DAY = {
    1: "sunny",
    2: "sunny",
    3: "partlycloudy",
    4: "partlycloudy",
    5: "rainy",
    6: "snowy-rainy",
    7: "snowy",
    8: "cloudy",
    9: "rainy",
    10: "rainy",
    11: "snowy",
    12: "snowy-rainy",
    13: "lightning-rainy",
    14: "fog",
    15: "fog",
    16: "lightning-rainy",
    17: "hail",
    18: "snowy",
    19: "hail",
    20: "hail",
    21: "partlycloudy",
    22: "sunny",
    23: "partlycloudy",
    24: "sunny",
}

# Valid HA weather conditions (homeassistant.components.weather).
HA_CONDITIONS = {
    "clear-night", "cloudy", "exceptional", "fog", "hail", "lightning",
    "lightning-rainy", "partlycloudy", "pouring", "rainy", "snowy",
    "snowy-rainy", "sunny", "windy", "windy-variant",
}


def test_map_covers_exactly_the_glossary():
    assert set(OUTLOOK_CONDITION_MAP) == set(GLOSSARY)


def test_every_value_is_a_valid_ha_condition():
    assert set(OUTLOOK_CONDITION_MAP.values()) <= HA_CONDITIONS


def test_day_conditions():
    for code, expected in EXPECTED_DAY.items():
        assert outlook_to_condition(code) == expected, code
        assert outlook_to_condition(code, is_night=False) == expected, code


def test_night_turns_only_sunny_into_clear_night():
    # Same rule as 1.1.4 (#7): HA has no night variant for partlycloudy.
    for code, day in EXPECTED_DAY.items():
        night = outlook_to_condition(code, is_night=True)
        if day == "sunny":
            assert night == "clear-night", code
        else:
            assert night == day, code


def test_codes_known_to_the_scraper_keep_their_condition():
    # Labels the 1.x scraper already mapped must not change behaviour.
    shared = {c: label for c, label in GLOSSARY.items() if label in CONDITION_TEXT_MAP}
    assert len(shared) == 12
    for code, label in shared.items():
        assert outlook_to_condition(code) == CONDITION_TEXT_MAP[label], (code, label)


def test_unknown_or_missing_code_is_none():
    assert outlook_to_condition(None) is None
    assert outlook_to_condition(None, is_night=True) is None
    assert outlook_to_condition(0) is None
    assert outlook_to_condition(25) is None
    assert outlook_to_condition(101) is None  # 1.x sprite night codes are not outlook codes


def test_every_outlook_in_the_fixtures_is_mapped():
    for name in ("api_daily_5658.json", "api_hourly_5658.json"):
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
            rows = json.load(f)[0]["forecasts"]
        for row in rows:
            assert outlook_to_condition(row["outlook"]) is not None, (name, row["outlook"])


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

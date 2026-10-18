<p align="center">
  <a href="https://www.ilmeteo.it/" target="_blank"><img src="https://raw.githubusercontent.com/giorgioparri/ha-ilmeteo/HEAD/images/logo.png" alt="iLMeteo.it" width="120"></a>
</p>

<p align="right"><a href="https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/README.it.md">🇮🇹 Leggi in italiano</a></p>

# iLMeteo.it — Home Assistant Custom Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/default)
[![GitHub Release](https://img.shields.io/github/release/giorgioparri/ha-ilmeteo.svg)](https://github.com/giorgioparri/ha-ilmeteo/releases)
[![Validate](https://github.com/giorgioparri/ha-ilmeteo/actions/workflows/validate.yml/badge.svg)](https://github.com/giorgioparri/ha-ilmeteo/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/giorgioparri/ha-ilmeteo)](https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/LICENSE)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=giorgioparri&repository=ha-ilmeteo&category=integration)

A [Home Assistant](https://www.home-assistant.io/) integration that exposes weather data from **[iLMeteo.it](https://www.ilmeteo.it/)** (a popular Italian weather service) as native `weather` entities, with **daily** and **hourly** forecasts — just like the OpenWeatherMap or Met.no integrations.

> **How it works:** since version 2.0 the integration uses iLMeteo.it's official API. Each user needs a personal API key, generated in their iLMeteo.it account area and entered once in Home Assistant.

---

## ⚠️ Important notes

- **An API key is required.** Generate it in your iLMeteo.it account area, then paste it when adding the integration. The key stays on your Home Assistant instance and is never part of this repository.
- **Daily limit:** each key has 1000 requests per day, reset at midnight Italian time and shared by every location using it. Refreshing every 30 minutes, one location uses about 100 requests a day. If the limit is reached, the last forecasts stay visible and keep advancing hour by hour, a notification is shown and updates resume after midnight.
- The integration shows the attribution "Dati meteo forniti da iLMeteo.it (www.ilmeteo.it)" on the entity.
- The device page (Settings → Devices & services → device) includes a "Visit" link to the location's page on iLMeteo.it.
- Independent project, published with the permission of iLMeteo Srl. Support is provided here on GitHub, not by iLMeteo.
- The "iLMeteo" logo and trademark are property of iLMeteo Srl and are used solely to identify the data source.

---

## Features

- Native `weather` entity with current conditions, apparent temperature, dew point, humidity, pressure, visibility, UV index, wind and gusts
- **Daily forecast** for 8 days, with min/max temperature, precipitation amount and probability, wind and pressure
- **Hourly forecast** until the end of the day after tomorrow, one slot per hour
- Day/night conditions from iLMeteo.it's own data (e.g. `sunny` → `clear-night`), and `pouring` for heavy rain
- **Location search** by name, by distance from your home, or by region and province — including hamlets and city districts
- **Multi-location** support: each location is a separate instance, all sharing the same key
- **Weather alert notifications**, on by default: heuristic thresholds on the same iLMeteo data, plus an optional official Protezione Civile source
- UI configuration — no YAML

## Screenshots

![iLMeteo.it weather card](https://raw.githubusercontent.com/giorgioparri/ha-ilmeteo/v2.0.0-beta.3/images/card-demo.png)

---

## Installation

### Via HACS (recommended)

1. Open HACS and search for **iLMeteo.it**
2. Install, then restart Home Assistant

The integration is in the HACS default catalogue: no custom repository needed.

### Manual

1. Download the latest [release](https://github.com/giorgioparri/ha-ilmeteo/releases/latest)
2. Copy `custom_components/ilmeteo` into `/config/custom_components/`
3. Restart Home Assistant

### Upgrading from 1.x

After the update and restart, Home Assistant asks to re-authenticate iLMeteo.it under **Settings → Devices & services**. Enter your API key once: it is used for every configured location. Locations, entities, options and history are kept. A one-time notification then lists the new optional sensors, which you can enable from **Configure**.

---

## Configuration

1. **Settings → Devices & Services → Add Integration → iLMeteo.it**
2. Enter your **API key** (asked only for the first location; the following ones suggest the same key)
3. Choose the location: **near your home location** (within 15 km), **search by name** (e.g. "Roma Monte Sacro"), or **region → province → location**
4. Optionally set a display name, the dedicated sensors and the alert notifications

Some hamlets and districts have no forecast of their own and use a nearby location's: the list says so next to the name. To add more locations, repeat the procedure.

### Entity naming and display name

Each instance gets a generic, permanent technical identifier — `weather.ilmeteo_site_1`, `weather.ilmeteo_site_2`, etc. — assigned once at creation and never reused, even if that instance is later removed.

The *displayed* name (shown in the UI, e.g. "iLMeteo.it Rome") is separate and fully customizable: you're asked for it during setup (defaulting to the chosen location, editable), and can change it any time afterward via the integration's **Configure** (Options) menu. Changing it never affects the technical entity ID — your automations and dashboards keep working regardless of what you rename things to.

### Changing the tracked location

Open the integration's three-dot menu → **Reconfigure** to point an existing instance at a different location (same choices as initial setup). This changes *where the data comes from*; the display name is reset to the new location's name (customize it again via Options if you'd like something else), while entity IDs, the device, and any enabled sensors are left untouched.

### Optional dedicated sensors

Besides the main `weather` entity, you can enable dedicated `sensor` entities — either during initial setup or any time afterward via **Configure** (Options):

- *Current hour:* temperature, apparent temperature, dew point, humidity, pressure, visibility, UV index, estimated solar irradiance, wind speed, wind gust, wind direction, precipitation in the hour, freezing level, snow level
- *Today:* minimum and maximum temperature, precipitation probability, total precipitation, forecast reliability

These exist specifically to support Home Assistant's long-term statistics and history graphs, which weather-entity attributes cannot provide (attributes have no `state_class`). They are **off by default** — nothing changes for existing installs until you opt in. Deselecting an enabled sensor deletes it, including its history.

### Weather alert notifications

**On by default** (toggle in the config flow at creation, and any time via **Configure** → Options). When enabled, each location is watched for weather alerts from up to two independent sources, evaluated in parallel:

- **Heuristic** (always on when alerts are enabled): threshold-based alerts — extreme heat/cold, strong wind, storms, hail, high rain probability — derived from the same forecast data already downloaded for the weather entity, with no extra requests. Evaluated separately for today and tomorrow. **Not an official alert**: the iLMeteo.it API has no alert data, so these thresholds are this integration's own (tunable in `alerts.py` if you disagree with them).
- **Protezione Civile** (optional): reads live alert data from the [DPC Alert](https://github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert) custom component by caiosweet, if you have it installed and configured for this location. No extra HTTP requests — this integration only reads the entity state that DPC Alert already keeps up to date.

**Which DPC entities to use:** DPC Alert exposes several entities; only two are useful here. Use **`sensor.dpc_alert`** (field `dpc_alert_entity_id`) for the official hydrogeological and hydraulic criticality bulletin (today and tomorrow, all risk types with severity level), and **`sensor.dpc_vigilance`** (field `dpc_vigilance_entity_id`) for the meteorological vigilance bulletin covering today, tomorrow and the day after (wind, snow, storms and other phenomena with distance and direction from your location). The two sensors are complementary and can both be active simultaneously. The six binary sensors (`dpc_idraulico_*`, `dpc_idrogeologico_*`, `dpc_temporali_*`) are simplified on/off views of the same data and are not needed here.

Both sources can be active at once — alerts from each carry a `source` attribute so you can tell them apart in automations.

Every alert notification includes a link to the location's iLMeteo.it page. Delivery:

- A `persistent_notification` is always created (and dismissed when the alert clears) — rendered with the iLMeteo logo and a clickable link in the HA frontend.
- Optionally, push to one or more **mobile devices with the companion app** via the `notify_targets` option (empty by default). The iLMeteo link is surfaced as a tappable action button ("Apri iLMeteo.it") since native push doesn't render Markdown. Only `notify.mobile_app_*` targets are supported — new-style notify entities (HA 2026.5+) don't yet support the companion-app data payload.
- An `ilmeteo_weather_alert` event is fired on every new, changed-severity, or cleared alert (`alert_id`, `severity`, `kind`, `title`, `message`, `source`, `link`, `cleared`), for building your own automations on top.

Alerts are deduplicated per `alert_id` + severity and persisted across restarts, so you're notified once when an alert first appears or worsens, not on every 30-minute refresh.

## Exposed data

**Current conditions** *(the forecast hour containing the current time)*: `condition`, `temperature`, `apparent_temperature`, `dew_point`, `humidity`, `pressure`, `visibility`, `uv_index`, `wind_speed`, `wind_gust_speed`, `wind_bearing`

**Daily forecast** *(8 days)*: condition, max/min temperature, precipitation amount and probability, pressure, wind speed, gust and bearing

**Hourly forecast** *(one slot per hour)*: condition, temperature, apparent temperature, dew point, humidity, precipitation, pressure, wind speed, gust and bearing, UV index

---

## Development & testing

The modules that talk to the API and decide what to do (`client.py`, `quota.py`, `update.py`, `alerts.py`, `const.py`) have no Home Assistant dependency, so their tests run as plain scripts. Only `aiohttp` is needed:

```bash
pip install aiohttp
python tests/test_api.py
python tests/test_quota.py
python tests/test_update.py
python tests/test_alerts.py
python tests/test_conditions.py
```

The API client tests run against a local fake gateway serving the JSON fixtures in `tests/fixtures/`: no API key and no network access are needed.

The modules that import Home Assistant (coordinator, config flow, entities, `alert_manager.py`) are not covered by these scripts; testing them needs `pytest-homeassistant-custom-component`.

---

## Changelog

See [CHANGELOG.md](https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/CHANGELOG.md) for the full version history.

---

## License

Apache-2.0 — see [LICENSE](https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/LICENSE)

## Disclaimer

This is an independent integration, published with the permission of iLMeteo Srl, which does not provide support for it. Weather data is retrieved from the iLMeteo.it API with your personal key. Use at your own risk and in accordance with iLMeteo's [terms of use](https://www.ilmeteo.it/portale/termini_e_condizioni).

## Acknowledgments

Built with the assistance of [Claude](https://claude.ai) by Anthropic.

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

A [Home Assistant](https://www.home-assistant.io/) integration that exposes weather data from **[iLMeteo.it](https://www.ilmeteo.it/)** (a popular Italian weather service) as native `weather` entities, with **daily** and **hourly** (3-hourly) forecasts — just like the OpenWeatherMap or Met.no integrations.

> **How it works:** iLMeteo's official REST API is reserved for business customers. Instead, this integration uses three of the **free public forecast box widgets** that iLMeteo provides for embedding on third-party sites (see the [business portals page](https://www.ilmeteo.it/business/portali)): a real-time conditions box for current weather, an official daily-summary box for accurate min/max and rain probability, and a 3-hourly box for detailed hourly forecasts. All are parsed server-side. No token required.

---

## ⚠️ Important notes

- This integration **scrapes** public web pages. There is no contractual stability guarantee: if iLMeteo changes a box's markup, the parser may need an update. Each of the three boxes is fetched independently, so a layout change on one doesn't take the others down — and a genuine parsing failure raises a visible warning in **Settings → System → Repairs** rather than failing silently.
- Out of respect for iLMeteo's [terms of use](https://www.ilmeteo.it/portale/termini_e_condizioni), the integration shows the attribution "Dati meteo forniti da iLMeteo.it (www.ilmeteo.it)" on the entity and polls at a low frequency (every 30 minutes).
- The device page (Settings → Devices & services → device) includes a "Visit" link to the configured municipality's page on iLMeteo.it.
- Unofficial project, not affiliated with iLMeteo Srl.
- The "iLMeteo" logo and trademark are property of iLMeteo Srl and are used solely to identify the data source.

---

## Features

- Native `weather` entity with **genuine real-time current conditions** (not an approximated forecast slot)
- **Daily forecast** up to 6 days using iLMeteo's own official daily min/max and **precipitation probability** — not derived from sparse hourly samples
- **Hourly forecast** (3-hourly): 5 slots per day with temperature, apparent temperature, humidity, wind, precipitation
- Automatic day/night condition handling (e.g. `sunny` → `clear-night`)
- **Multi-location** support: each city is a separate instance
- **Weather alert notifications**, on by default: heuristic thresholds on the same iLMeteo data, plus an optional official Protezione Civile source
- UI configuration — no YAML, no token

## Screenshots

![iLMeteo.it weather card](https://raw.githubusercontent.com/giorgioparri/ha-ilmeteo/v1.2.2/images/card-demo.png)

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

---

## Configuration

1. **Settings → Devices & Services → Add Integration → iLMeteo.it**
2. Select **region**, then **province**, then **municipality** from the dropdowns
3. Done: the entity is created and validated automatically

The full list of Italian municipalities (8,218 municipalities, 110 provinces, 20 regions) is bundled with the integration, so there is no need to look up codes manually. To add more locations, repeat the procedure.

> The dataset is generated from iLMeteo's official location codes via
> `scripts/build_locations.py` and stored compressed (~67 KB) in
> `custom_components/ilmeteo/data/locations.json.gz`.

### Entity naming and display name

Each instance gets a generic, permanent technical identifier — `weather.ilmeteo_site_1`, `weather.ilmeteo_site_2`, etc. — assigned once at creation and never reused, even if that instance is later removed.

The *displayed* name (shown in the UI, e.g. "iLMeteo.it Rome") is separate and fully customizable: you're asked for it during setup (defaulting to the chosen municipality, editable), and can change it any time afterward via the integration's **Configure** (Options) menu. Changing it never affects the technical entity ID — your automations and dashboards keep working regardless of what you rename things to.

### Changing the tracked location

Open the integration's three-dot menu → **Reconfigure** to point an existing instance at a different municipality (same region/province/municipality picker as initial setup). This changes *where the data comes from*; the display name is reset to the new municipality's name (customize it again via Options if you'd like something else), while entity IDs, the device, and any enabled sensors are left untouched.

### Optional dedicated sensors

Besides the main `weather` entity, you can enable dedicated `sensor` entities — either during initial setup or any time afterward via **Configure** (Options):

- Temperature, humidity, wind speed, wind direction *(current readings)*
- Daily minimum and maximum temperature, precipitation probability *(today only — never derived from the multi-day forecast)*

These exist specifically to support Home Assistant's long-term statistics and history graphs, which weather-entity attributes cannot provide (attributes have no `state_class`). They are **off by default** — nothing changes for existing installs until you opt in. Deselecting an enabled sensor deletes it, including its history.

### Weather alert notifications

**On by default** (toggle in the config flow at creation, and any time via **Configure** → Options). When enabled, each location is watched for weather alerts from up to two independent sources, evaluated in parallel:

- **Heuristic** (always on when alerts are enabled): threshold-based alerts — extreme heat/cold, strong wind, storms, hail, high rain probability — derived from the same real1/day1/tri1 data already scraped for the weather entity. Evaluated separately for today and tomorrow. **Not an official alert**: iLMeteo.it does not publish structured alert data in its public box widgets, only editorial articles, so these thresholds are this integration's own (tunable in `alerts.py` if you disagree with them).
- **Protezione Civile** (optional): reads live alert data from the [DPC Alert](https://github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert) custom component by caiosweet, if you have it installed and configured for this location. No extra HTTP requests — this integration only reads the entity state that DPC Alert already keeps up to date.

**Which DPC entities to use:** DPC Alert exposes several entities; only two are useful here. Use **`sensor.dpc_alert`** (field `dpc_alert_entity_id`) for the official hydrogeological and hydraulic criticality bulletin (today and tomorrow, all risk types with severity level), and **`sensor.dpc_vigilance`** (field `dpc_vigilance_entity_id`) for the meteorological vigilance bulletin covering today, tomorrow and the day after (wind, snow, storms and other phenomena with distance and direction from your location). The two sensors are complementary and can both be active simultaneously. The six binary sensors (`dpc_idraulico_*`, `dpc_idrogeologico_*`, `dpc_temporali_*`) are simplified on/off views of the same data and are not needed here.

Both sources can be active at once — alerts from each carry a `source` attribute so you can tell them apart in automations.

Every alert notification includes a link to the location's iLMeteo.it page. Delivery:

- A `persistent_notification` is always created (and dismissed when the alert clears) — rendered with the iLMeteo logo and a clickable link in the HA frontend.
- Optionally, push to one or more **mobile devices with the companion app** via the `notify_targets` option (empty by default). The iLMeteo link is surfaced as a tappable action button ("Apri iLMeteo.it") since native push doesn't render Markdown. Only `notify.mobile_app_*` targets are supported — new-style notify entities (HA 2026.5+) don't yet support the companion-app data payload.
- An `ilmeteo_weather_alert` event is fired on every new, changed-severity, or cleared alert (`alert_id`, `severity`, `kind`, `title`, `message`, `source`, `link`, `cleared`), for building your own automations on top.

Alerts are deduplicated per `alert_id` + severity and persisted across restarts, so you're notified once when an alert first appears or worsens, not on every 30-minute refresh.

## Exposed data

**Current conditions** *(real-time box)*: `temperature`, `humidity`, `wind_speed`, `wind_bearing`, `condition`

**Daily forecast** *(official daily-summary box)*: max/min temperature, **precipitation probability**, wind, condition, plus total precipitation amount (from the hourly box)

**Hourly forecast** *(3-hourly box)*: for each 3-hour slot → temperature, apparent temperature, humidity, wind, precipitation, condition

---

## Development & testing

The HTML parser is isolated in `api.py` (`parse_box`) with no Home Assistant dependency, so it can be tested directly:

```bash
python tests/test_parser.py
```

The tests use a real HTML fixture in `tests/fixtures/`.

Alert providers (`alerts.py`) are also free of Home Assistant dependencies — `HeuristicAlertProvider` is pure, and `DpcSensorAlertProvider` only needs `hass.states.get()`, stubbed with a minimal fake:

```bash
python tests/test_alerts.py
```

`IlMeteoAlertManager` (dedup/persistence/notification dispatch in `alert_manager.py`) is not covered here — it imports `homeassistant.core`/`homeassistant.helpers.storage` directly, so testing it would need `pytest-homeassistant-custom-component` rather than this dependency-free setup.

To regenerate the bundled location dataset from the official iLMeteo CSV files:

```bash
python scripts/build_locations.py codici_comuni.csv codici_province.csv \
  custom_components/ilmeteo/data/locations.json.gz
```

---

## Changelog

See [CHANGELOG.md](https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/CHANGELOG.md) for the full version history.

---

## License

Apache-2.0 — see [LICENSE](https://github.com/giorgioparri/ha-ilmeteo/blob/HEAD/LICENSE)

## Disclaimer

This is an unofficial integration and is not affiliated with, endorsed by, or supported by iLMeteo Srl. Weather data is retrieved from the publicly available iLMeteo.it forecast box. Use at your own risk and in accordance with iLMeteo's [terms of use](https://www.ilmeteo.it/portale/termini_e_condizioni).

## Acknowledgments

Built with the assistance of [Claude](https://claude.ai) by Anthropic.

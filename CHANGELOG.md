# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.2.2] - 2026-09-28

### Changed
- The project moved to the GitHub username `giorgioparri` (previously `naked-head`): links in the README, documentation, issue tracker and code owner are updated. Nothing to do — existing installations keep working and GitHub redirects the old repository URLs.
- The header logo is referenced at `HEAD` instead of `main`, so it keeps resolving if the default branch is ever renamed.
- The release workflow now checks that the card screenshot is pinned to the tag being released, so the README shown in HACS matches the installed version.

### Fixed
- Links to other files in the repository are absolute, so they work in the README rendered by HACS. Relative targets are blanked by Home Assistant's markdown sanitiser, which left the links dead exactly where users read the page.

## [1.2.1] - 2026-08-28

### Changed
- Relicensed from GPL-3.0-or-later to Apache-2.0.

## [1.2.0] - 2026-08-24

### Changed
- HACS now installs from the release ZIP asset (`zip_release`), so download counts are tracked correctly.

## [1.1.4] - 2026-08-09
### Fixed
- Weather entity showed `sunny` instead of `clear-night` at night with clear skies (closes #7). Root cause: iLMeteo's `real1` box never uses night condition codes (≥100), unlike `tri1`. Fixed by applying night correction in `weather.py` independently of the condition code: current conditions use `homeassistant.helpers.sun.is_up()`, hourly forecast slots use a time-of-day heuristic (21:00–06:00). Daily forecasts are unaffected.

## [1.1.3] - 2026-07-21
### Changed
- DPC alert messages now follow the same format used by iLMeteo.it: "Protezione Civile: [Ordinaria/Moderata/Elevata] criticità per rischio [Tipo]". Added `DPC_LEVEL_LABEL` mapping (level 2→Ordinaria, 3→Moderata, 4→Elevata). Applied consistently to `DpcSensorAlertProvider`, its legacy fallback, and `DpcVigilanceProvider` (both the day-level alert and per-phenomenon messages).

## [1.1.2] - 2026-07-13
### Fixed
- Critical: `NameError: name 'link' is not defined` in `alert_manager._evaluate()` introduced in 1.1.1 prevented the integration from setting up and silently dropped all notifications. (Moved from 1.1.1 changelog entry to this dedicated release.)
- Reconfigure flow now pre-selects the currently configured region, province and city instead of defaulting to the first alphabetical entry. Added `location_data.lookup_location()` for reverse lookup of a city code to its region/province/city name.

## [1.1.1] - 2026-07-09
### Added
- Hysteresis for heuristic alert thresholds: once an alert is active, it is kept alive until the value drops a fixed delta below the trigger threshold, preventing rapid on/off oscillation when values hover near a boundary between 30-minute refreshes. Deltas: heat/cold ±2°C, wind ±5 km/h, rain probability ±5%. Storm and hail alerts have no hysteresis (condition_text is binary).
- `active_alert_ids` parameter added to `AlertProvider.async_get_alerts()` ABC; all providers accept it (DPC providers ignore it as their data is already authoritative).

## [1.1.0] - 2026-07-06
### Changed
- **Batched notifications per day**: all active alerts for the same day (today / tomorrow / day-after-tomorrow) are now grouped into a single `persistent_notification` and a single mobile push, instead of one notification per alert. The notification is re-rendered when the set of alerts for that day changes (new alert, severity change, or cleared alert) and dismissed when no alerts remain. This eliminates the "3 simultaneous notifications" noise from vigilance bulletins carrying multiple phenomena.
- `WeatherAlert` now carries a `day` field (`today` / `tomorrow` / `aftertomorrow`), populated by all providers and included in the `ilmeteo_weather_alert` event payload.
- The `ilmeteo_weather_alert` event is still fired once per individual alert (unchanged granularity for automations); only the visual rendering is batched.

## [1.0.1] - 2026-07-03
### Fixed
- `DpcVigilanceProvider`: phenomena were evaluated regardless of the day's alert level, causing spurious alerts when the day level was below the threshold (level < 2). Phenomena are now skipped entirely when the day level does not meet the threshold.
- `DpcVigilanceProvider`: distance and direction (zone centroid coordinates) are now included in the alert message only for spatially localised phenomena (Venti, Temporali, Neve, Mare, Ghiaccio). Temperature phenomena no longer show a misleading "a X km in direzione Y" suffix.

## [1.0.0] - 2026-07-03
### Added
- First stable public release.

### Changed
- Version bumped to 1.0.0 to reflect production-ready status ahead of HACS default submission.

## [0.7.5] - 2026-07-02
### Added
- `DpcVigilanceProvider`: reads `sensor.dpc_vigilance` from the [DPC Alert](https://github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert) integration (optional, configured via the new `dpc_vigilance_entity_id` option). Covers today, tomorrow and day-after-tomorrow. Generates alerts for the overall level (precipitation quantity) and for each nearby meteorological phenomenon (wind, snow, storms, etc.) with distance and direction. Complementary to the existing `sensor.dpc_alert` provider.
- Italian README (`README.it.md`) with full translation and a link to the English version.

### Changed
- DPC entity selection table in both READMEs updated: `sensor.dpc_vigilance` now shows as actively supported (no longer "future release"), with field name references and a note on complementarity.
- Config flow step descriptions updated to explain both DPC fields.

## [0.7.4] - 2026-07-02
### Fixed
- Push notifications: `notify_targets` selector now restricted to `mobile_app_*` services (the only ones supporting companion-app `data` payload with image and URI action button). New-style notify entities (HA 2026.5+) are excluded as they don't support these fields yet — see [HA discussion #3684](https://github.com/orgs/home-assistant/discussions/3684).
- Push notifications: companion-app service (`notify.mobile_app_*`) registers a few seconds after HA setup; added retry logic (up to 5 attempts, 10s apart) to avoid silently dropping alerts sent at boot.
- `bus.async_fire` for `ilmeteo_weather_alert` event was incorrectly placed inside `_push_with_retry`, causing it to never fire when no push targets were configured. Moved to `_notify` so it always fires unconditionally.
- `persistent_notification`: iLMeteo logo now rendered at 72px in a table layout with text alongside, instead of full-width.

### Changed
- `notify_targets` field label updated to clarify only mobile devices with the companion app are supported.
- Config flow step descriptions restructured with bold section headings and a direct link to the [DPC Alert](https://github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert) integration.

## [0.7.2] - 2026-07-02
### Changed
- Config flow: improved step descriptions with structured sections (bold headings, blank lines) and a direct link to the [DPC Alert](https://github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert) integration where the Civil Protection entity field is explained.
- `dpc_alert_entity_id` field label simplified to "Entità allerta Protezione Civile (opzionale)" / "Civil Protection alert entity (optional)".

## [0.7.1] - 2026-07-02
### Fixed
- Config flow: `dpc_alert_entity_id` left blank caused "Entity None is neither a valid entity ID nor a valid UUID" on the next Options open. Fixed by using `vol.UNDEFINED` as the field default and sanitizing `None` values via a centralized `_clean_options()` before saving to the config entry.

### Changed
- `notify_targets` multi-select was already functional; the crash above prevented testing it in practice.
- DPC Alert entity field now shows a description with a link to the [DPC Alert](https://github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert) integration directly in the config flow.

## [0.7.0] - 2026-07-01
### Added
- Weather alert notifications, on by default (toggle in the config flow at creation, and any time via Options):
  - `HeuristicAlertProvider`: threshold-based alerts (extreme heat/cold, strong wind, storms, hail, high rain probability) derived from the same real1/day1/tri1 data already scraped for the weather entity — not an official alert source, since iLMeteo.it does not expose structured alert data in its public box widgets. Evaluates today and tomorrow independently.
  - Optional `DpcSensorAlertProvider`: reads an existing `sensor.dpc_alert` entity from the [DPC Alert](https://github.com/caiosweet/Home-Assistant-custom-components-DPC-Alert) custom component, if installed and pointed to via the new `dpc_alert_entity_id` option — official Protezione Civile data, no extra HTTP requests of our own.
  - Every alert notification includes a link to the location's iLMeteo.it page.
  - Native `persistent_notification` always created/dismissed per alert; optional push to one or more `notify.*` targets via the new `notify_targets` option (empty by default).
  - `ilmeteo_weather_alert` event fired on every new/changed/cleared alert, for building custom automations.
  - Per-alert dedup persisted across restarts (`homeassistant.helpers.storage.Store`): notifies only on a new alert or a severity change, not on every 30-minute refresh.

## [0.6.2] - 2026-06-24
### Added
- Device page now links to the configured municipality's iLMeteo.it page (`configuration_url`), shown automatically as a "Visit" link on Settings → Devices & services → device page.

## [0.6.1] - 2026-06-21
### Fixed
- Entity IDs were not actually location-independent (`weather.ilmeteo_it_roma_ilmeteo_site_2` instead of `weather.ilmeteo_site_2`); fixed by setting `entity_id` directly.
- Reconfigure now also updates the config entry title, not just the device name.
### Added
- Sensor selection is now offered during initial setup, not only via Options.
- Custom display name, editable at creation and any time via Options.
- 3 more optional sensors: wind direction, daily min/max temperature. 7 total.
### Changed
- Reconfigure resets the display name to the new municipality (editable again via Options).

## [0.6.0] - 2026-06-21
### Added
- Optional dedicated sensors (temperature, humidity, precipitation probability, wind speed) via Options flow. Off by default.
- Reconfigure flow: change tracked municipality without recreating the integration.
### Changed
- Entity identifiers decoupled from location: `unique_id` tied to the config entry, entity IDs generic and sequential (`weather.ilmeteo_site_1`, ...), never reused. Display name still tracks location.
- Deselecting a sensor deletes it and its history.
### Notes
- From-scratch redesign of entity identity; no migration path from pre-0.6.0 IDs.

## [0.5.1] - 2026-06-20
### Added
- Diagnostics platform: download button exporting tracked location, last update status, and cached box data.

## [0.5.0] - 2026-06-20
### Added
- CI workflow running the test suite on every push/PR (Python 3.12/3.13).
- Home Assistant Repair issues for genuine box parsing failures, auto-clearing on recovery.
### Changed
- Each box (real1/day1/tri1) fetched and parsed independently; a failure on one falls back to last-known-good data instead of failing the whole update.
- `async_unload_entry` clears open Repair issues on removal.

## [0.4.1] - 2026-06-20
### Fixed
- `parse_real1` rewritten against genuine HTML: styled `<b>` tag, HTML entities, unrelated `<a>` link.
### Changed
- Day/night handling now uses real1's own sprite code instead of a fixed hour range.
### Added
- Regression tests for the issues above.

## [0.4.0] - 2026-06-20
### Added
- True real-time current conditions from the `real1` box.
- Daily min/max sourced from the official `day1` box instead of derived from hourly samples.
- `precipitation_probability` field on the daily forecast.
- Unit tests for both new parsers.
### Changed
- Removed the "closest forecast slot" matching logic for current conditions.
### Removed
- Daily-low and current-conditions approximation caveats from the README (now fully resolved).

## [0.3.4] - 2026-06-20
### Fixed
- Timezone bug: `dt_util.as_local()` on naive local datetimes shifted forecast slot times by the UTC offset. Fixed by attaching local tzinfo directly.

## [0.3.3] - 2026-06-19
### Fixed
- README: relative image/link paths replaced with absolute URLs (HACS does not resolve relative paths).
### Added
- README: HACS direct-install button, demo screenshot.

## [0.3.2] - 2026-06-19
### Changed
- Extended entity attribution to "Dati meteo forniti da iLMeteo.it (www.ilmeteo.it)".

## [0.3.1] - 2026-06-19
### Changed
- Device name extended to `iLMeteo.it <location>`.
### Added
- Official iLMeteo.it logo as integration icon and in the README.

## [0.3.0] - 2026-06-19
### Added
- Cascading location selection: region → province → municipality.
- Bundled dataset of 8,218 Italian municipalities (~67 KB compressed).
- Dataset regeneration script.
- Unit tests for the location dataset.

## [0.2.0] - 2026-06-19
### Changed
- Backend rewrite: from REST client (enterprise-only API) to public box widget scraping.
### Added
- Daily and hourly (3-hourly) forecasts.
- Automatic day/night condition handling.
- Regex-based HTML parser with unit tests.

## [0.1.0] - 2026-06-12
### Added
- Initial draft based on the official iLMeteo REST API (later abandoned, enterprise-only).

[Unreleased]: https://github.com/giorgioparri/ha-ilmeteo/compare/v1.2.2...HEAD
[1.2.2]: https://github.com/giorgioparri/ha-ilmeteo/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/giorgioparri/ha-ilmeteo/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/giorgioparri/ha-ilmeteo/compare/v1.1.4...v1.2.0
[1.1.4]: https://github.com/giorgioparri/ha-ilmeteo/compare/v1.1.3...v1.1.4
[1.1.3]: https://github.com/giorgioparri/ha-ilmeteo/compare/v1.1.2...v1.1.3
[1.1.2]: https://github.com/giorgioparri/ha-ilmeteo/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/giorgioparri/ha-ilmeteo/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/giorgioparri/ha-ilmeteo/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/giorgioparri/ha-ilmeteo/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.7.5...v1.0.0
[0.7.5]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.7.4...v0.7.5
[0.7.4]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.7.3...v0.7.4
[0.7.3]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.7.2...v0.7.3
[0.7.2]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.6.2...v0.7.0
[0.6.2]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.3.4...v0.4.0
[0.3.4]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/giorgioparri/ha-ilmeteo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/giorgioparri/ha-ilmeteo/releases/tag/v0.1.0
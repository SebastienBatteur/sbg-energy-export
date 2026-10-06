# SBG Energy Export (Home Assistant)

*[Version française](README.md)*

Exports the data of the Home Assistant **Energy dashboard** to the open **"SBG HA export"**
format ([specification, in French](docs/FORMAT_SBG_HA_EXPORT.md)), so that you can upload it
yourself to an analysis service such as analyse.sbg-energy.com.

- **Nothing is sent anywhere.** The integration makes no outbound network call: you download the
  file from your own Home Assistant and upload it wherever you choose.
- **Only what is needed**: grid (import, export), solar, battery (charge, discharge), home
  consumption, and the devices **you** choose (all, none, or a selection) under a neutral name
  (`voiture_1`, `pac_1`…). No device name, room, entity ID or location.
- **Quarter-hours from installation onwards**: Home Assistant keeps hourly long-term statistics
  forever, but deletes its 5-minute short-term statistics after 10 days (`purge_keep_days`). The
  integration therefore records every quarter-hour as it goes.

> Status: **version 0.1.0, not published yet**. Name, licence and publication still to be decided.

## What the export contains

| Period | Resolution | Provenance in the file |
|---|---|---|
| Before installation (back to the start of your statistics) | hour | `mesure_60min`, or `heure_repartie` (hour split in 4) in a 15-min file |
| ~10 days before installation, and onwards | quarter-hour | `mesure_15min` |
| Missing data | — | `trou` (empty cells) |

An empty cell means "unknown", never zero.

## Installation

Requires Home Assistant **2026.9** or later (tested with 2026.10.0b0) and a **configured Energy
dashboard** (at least grid, solar or a battery).

**HACS (custom repository)**: HACS → ⋮ → *Custom repositories* → this repository's URL, category
*Integration* → install *SBG Energy Export* → restart Home Assistant.

**Manual**: copy `custom_components/sbg_energy_export` into the `custom_components` folder of your
configuration → restart Home Assistant.

Then **Settings → Devices & services → Add integration → SBG Energy Export**.

## Configuration

1. **Devices to export**: *All*, *None* or *A selection* of the Energy dashboard's individual devices.
2. **Category** of each selected device: electric car, heat pump, water heater, cooking, other.
   A category is suggested from the device name; correct it if needed.

Change it later with **Configure** on the integration card.

## Usage

- **Export (15 min)** and **Export (hourly)** buttons on the *SBG Energy Export* device;
- or the `sbg_energy_export.exporter` action (fields `pas`: 15 or 60, `debut`, `fin`: UTC dates,
  end excluded); it returns the file name and the link.

A **notification** shows a **Download** link served by your Home Assistant, valid for one hour.
The file also stays in `<config>/sbg_energy_export/exports/`.

The **Last recorded quarter-hour** diagnostic sensor shows that recording is running (attribute:
first recorded quarter-hour).

## What is stored on your system

- `<config>/sbg_energy_export/quarts/quarts_YYYY-MM.csv`: one file per month, one line per
  quarter-hour and per Energy-dashboard statistic (`debut_utc,statistique,kwh`), about 20 MB a year
  for 10 statistics. These files contain your sensors' IDs: they stay inside Home Assistant, like
  its own database. All dashboard statistics are recorded so that you can change your selection
  later without losing history; selection and anonymisation apply at export time.
- `<config>/sbg_energy_export/exports/`: the exports produced (delete them whenever you like).
- `.storage/sbg_energy_export.collecteur`: the last processed quarter-hour.

On start-up, the integration catches up on missing quarter-hours as long as Home Assistant still
holds their 5-minute statistics (~10 days); a longer outage leaves a gap, filled at export time by
the hour split in four.

## Without the integration

See [docs/PROCEDURE_MANUELLE.md](docs/PROCEDURE_MANUELLE.md) (French) and the script
[`outils/sbg_ha_export.py`](outils/sbg_ha_export.py) (Python 3.9+, standard library only): from
Energy-dashboard downloads, or with a long-lived access token you create yourself.

## Development

- `custom_components/sbg_energy_export/sbg_format.py`: the format, in pure Python, shared with the
  manual script (`outils/assembler_script.py` copies the block; a test checks they are identical).
- Tests: `pytest` with `pytest-homeassistant-custom-component` (Linux or WSL; Home Assistant does
  not run on Windows), with a real in-memory SQLite recorder:

  ```
  pip install -r requirements_test.txt
  pytest
  ```

## Licence

Proposed: MIT (see [LICENSE](LICENSE)), to be confirmed.

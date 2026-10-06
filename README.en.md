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
  integration picks up those ~10 days at installation, then records every quarter-hour (or,
  optionally, every 5-minute period) as it goes.

> Status: **version 0.2.0, not published yet**. Name, licence and publication still to be decided.

## What the export contains

| Period | Resolution | Provenance in the file |
|---|---|---|
| Before installation (back to the start of your statistics) | hour | `mesure_60min`, or `heure_repartie` (hour split in 4, or in 12 at the 5-min step) |
| ~10 days before installation, and onwards | quarter-hour | `mesure_15min` |
| same, with the "finest step: 5 minutes" option | 5 minutes | `mesure_5min` (5-min file) |
| Missing data | — | `trou` (empty cells) |

From day one, an export therefore holds the whole past hourly and the last ~10 days at the fine
step. An empty cell means "unknown", never zero.

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
   The screen lists them from the most to the least useful for the analysis: large and
   controllable loads (car, heat pump, hot water), then cooking and washing, then base load
   (cold, IT, lighting), with one sentence on why; recommended ones are ticked by default, you
   remain free to choose.
2. **Category** of each selected device: car / charger, heat pump / heating, hot water, cooking,
   washing, cold, IT and network, lighting, other. It is suggested by fixed rules (no AI): the
   name, then the Home Assistant device (name, model, manufacturer), then the typical power (an
   hour at 5.5 kWh or more = car charging); correct it if needed.
3. **Keep local data** (years, **3** by default): older months are deleted.
4. **Finest step: 5 minutes** (off by default): keeps 5-minute periods instead of quarter-hours.
   A finer resolution helps recognise devices (starts, cycles); it takes about 2.5 times more
   space. Exports can then be made at 5 or 15 minutes.

Change it later with **Configure** on the integration card.

## Usage

- **Export (15 min)** and **Export (hourly)** buttons on the *SBG Energy Export* device, plus
  **Export (5 min)** with the 5-minute option;
- or the `sbg_energy_export.exporter` action (fields `pas`: 5, 15 or 60, `debut`, `fin`: UTC
  dates, end excluded); it returns the file name and the link.

A **notification** shows a **Download** link served by your Home Assistant, valid for one hour.
The file also stays in `<config>/sbg_energy_export/exports/`.

The **Last recorded quarter-hour** diagnostic sensor shows that recording is running (attribute:
first recorded quarter-hour).

## What is stored on your system

- `<config>/sbg_energy_export/mesures/mesures_15min_YYYY-MM.csv` (or `mesures_5min_…`): one file
  per (UTC) month, one line per period and one column per statistic. The current month is plain
  text; every **finished month is compressed** (`.csv.gz`); exports read both transparently.
  Months older than the **retention period** are deleted.
- **Only what is needed**: the Energy dashboard's grid, solar and battery sources, and the devices
  you chose. These files contain your sensors' IDs: they stay inside Home Assistant, like its own
  database; anonymisation applies at export time.
- A device **added** later is recorded from then on, and caught up over the ~10 days for which
  Home Assistant still holds its 5-minute statistics. A device **removed** is no longer recorded
  or exported; what was already recorded stays until the end of the retention period (fine
  history cannot be rebuilt, and a device unticked by mistake gets its past back).
- Space measured over one simulated year with 10 devices (`outils/mesurer_stockage.py`):
  **≈ 0.4 MB** at 15 minutes, **≈ 1 MB** at 5 minutes (up to ≈ 0.7 and 1.8 MB with meters finer
  than 1 Wh).
- `<config>/sbg_energy_export/exports/`: the exports produced (delete them whenever you like).
- `.storage/sbg_energy_export.collecteur`: the last processed period and the recorded statistics.

On start-up, the integration catches up on missing periods as long as Home Assistant still holds
their 5-minute statistics (~10 days); a longer outage leaves a gap, filled at export time by the
split hour. Files from version 0.1.0 (`quarts/`) are converted automatically.

## Without the integration

See [docs/PROCEDURE_MANUELLE.md](docs/PROCEDURE_MANUELLE.md) (French):

- **without a token**: the hourly export of the HACS integration
  [Import Statistics](https://github.com/klausj1/homeassistant-statistics) (klausj1) can be
  uploaded to the service as is;
- **with a long-lived access token** you create yourself: the script
  [`outils/sbg_ha_export.py`](outils/sbg_ha_export.py) (Python 3.9+, standard library only)
  produces an "SBG HA export" file.

## Development

- `custom_components/sbg_energy_export/sbg_format.py`: the format, in pure Python, shared with the
  manual script (`outils/assembler_script.py` copies the block; a test checks they are identical).
- `custom_components/sbg_energy_export/stockage.py`: local storage (pure Python).
- `outils/mesurer_stockage.py`: measures storage and export size over a simulated year.
- `custom_components/sbg_energy_export/categories.py`: suggested categories and recommended devices (fixed rules).
- `docs/icone/`: icon (SVG, 256 and 512 px PNG), drawn in-house.
- Tests: `pytest` with `pytest-homeassistant-custom-component` (Linux or WSL; Home Assistant does
  not run on Windows), with a real in-memory SQLite recorder:

  ```
  pip install -r requirements_test.txt
  pytest
  ```

## Licence

[Apache-2.0](LICENSE) (see also [NOTICE](NOTICE)).

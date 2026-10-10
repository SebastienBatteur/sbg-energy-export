# SBG Energy Export (Home Assistant)

<img src="https://raw.githubusercontent.com/SebastienBatteur/sbg-energy-export/main/docs/icone/icon.png" alt="SBG Energy logo" width="96" height="96">

*[Version française](README.md)*

Overview and how-to: https://sbg-energy.com/donnees-compteur/#home-assistant

Exports the data of the Home Assistant **Energy dashboard** to the open **"SBG HA export"**
format ([specification, in French](docs/FORMAT_SBG_HA_EXPORT.md)), so that you can upload it
yourself to an analysis service such as analyse.sbg-energy.com.

- **Nothing is sent anywhere, by default.** You download the export from your own Home Assistant
  and upload it wherever you choose. **Direct sending** to analyse.sbg-energy.com
  ([below](#direct-sending-to-analysesbg-energycom-optional-off-by-default)) is **off by default**:
  only if you turn it on and connect your SBG Energy account.
- **Only what is needed**: grid (import, export), solar, battery (charge, discharge), home
  consumption, and the devices **you** choose (all, none, or a selection) under a neutral name
  (`voiture_1`, `pac_1`…). No device name, room, entity ID or location.
- **Quarter-hours from installation onwards**: Home Assistant keeps hourly long-term statistics
  forever, but deletes its 5-minute short-term statistics after 10 days (`purge_keep_days`). The
  integration picks up those ~10 days at installation, then records every quarter-hour (or,
  optionally, every 5-minute period) as it goes.

> Status: **version 0.6.2, beta**. Apache-2.0 licence. User interface in English, French, Dutch and
> German. Problems and ideas: [issues](https://github.com/SebastienBatteur/sbg-energy-export/issues);
> security vulnerabilities: see [SECURITY.md](SECURITY.md). Version history: [CHANGELOG.md](CHANGELOG.md).

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

**HACS (custom repository)**: HACS → ⋮ → *Custom repositories* → `https://github.com/SebastienBatteur/sbg-energy-export`, category
*Integration* → install *SBG Energy Export* → restart Home Assistant.

**Manual**: copy `custom_components/sbg_energy_export` into the `custom_components` folder of your
configuration → restart Home Assistant.

Then **Settings → Devices & services → Add integration → SBG Energy Export**.

## Configuration

1. **Devices to export**: *All*, *None* or *A selection* of the Energy dashboard's individual devices.
   The screen lists them from the most to the least useful for the analysis: large and
   controllable loads (car, heat pump, hot water), then cooking and washing, then base load
   (cold, IT, lighting, ventilation, pumps), with one sentence on why; recommended ones are ticked by default, you
   remain free to choose.
2. **Category** of each selected device: car / charger, heat pump / heating, hot water, cooking,
   washing, cold, IT and network, lighting, ventilation, pumps and water, other. It is suggested by fixed rules (no AI): the
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

A **notification** shows a **Download** link served by your Home Assistant, valid for one hour; it opens in a new tab, which downloads the file (if nothing happens: right-click → "Open in new tab"). The file is a **ZIP archive** holding the CSV (format version 2 at 5 and 15 minutes: the past stays one line per hour): upload it as is to analyse.sbg-energy.com. It stays in `<config>/sbg_energy_export/exports/`.

The **Last recorded quarter-hour** diagnostic sensor shows that recording is running (attribute:
first recorded quarter-hour).

## Direct sending to analyse.sbg-energy.com (optional, off by default)

Instead of downloading the file and uploading it yourself, the integration can send it **by
itself** to SBG Energy's analysis service. **Nothing is sent until you turn it on AND connect
your account.** It is the integration's **only outgoing network call**.

1. **Configure** → last step **"Send to analyse.sbg-energy.com"** → tick **Send to
   analyse.sbg-energy.com**, give your **postcode** (required: Home Assistant does not know it;
   it is used for grid tariffs, region and the area's weather, never for an address), your
   **distribution system operator** if you know it (optional: "I don't know" by default, the
   service then infers it from the postcode when only one is possible), choose the step (15 min
   or hourly; 5 min with the 5-minute option) and, if you wish, tick **Improve SBG tools** (see
   below; unticked by default).
2. The screen shows a **link** and a **code**: open the link (phone or computer), sign in to your
   **SBG Energy account** (with your 6-digit code), enter the code and accept. That's all: **once**.
   - No password or secret is stored in Home Assistant: only a revocable **token**, kept in the
     config entry and never written to the logs.
3. The postcode and the tick box reach the service right after the connection: the report is
   computed from the first send. **At most three Home Assistant installations per account**: the
   fourth is refused at this step (nothing is enabled, the token is withdrawn); you can disconnect
   one from your account. Changing the postcode, the operator or the tick box later, in the same
   step, makes one call to the service when you save (account connected).
4. **Your home**: the data join a home of your SBG Energy account, and its report uses them. When
   the service says so, the integration shows that home right after the connection and, if your
   account has several, lets you choose another one (there, or later in the Send step).
   Otherwise the service files the installation by postcode.

What is sent, and when:

- **The same content as the manual export**: the chosen devices, no entity name, at the chosen
  step; complete UTC days only.
- **At most one automatic send per month**, from the 2nd (the past month, plus any missing day);
  the first time, **the whole available history** (3 years at most). Before each send, the
  integration asks the service which days it already has and **sends only the missing ones**. The
  limit is **enforced by the service**: the **Send now** button (and the
  `sbg_energy_export.envoyer` action) is subject to it too.
- **Re-import** (`sbg_energy_export.reimporter` action, fields `debut` and `fin`, UTC dates, end
  excluded): sends the period again and **replaces** those days at the service. **3 times per
  month** at most.
- **5-minute step**: the service and the integration keep it for 12 months only; older days are
  sent at 15 minutes, in the same send.
- **500 MB at most** per account at the service (a clear message says so beyond).
- Once a week the integration renews its token at **auth.sbg-energy.com** (no data at all);
  otherwise the connection would expire after 30 days unused.

What the service does with it: **the report of your home**, updated at each send, and a
**"better offer" e-mail alert** (no consumption data in it). The 5-minute step is kept **12
months** there (to understand behaviours), then grouped into quarter-hours (to follow their
evolution); everything is deleted after **3 rolling years**, erasable from your account, erased if
you delete your account. **Free during the beta.**

**Improve SBG tools** (optional tick box, **unticked by default**, the same as on the upload form:
"I agree that SBG keeps my consumption data, pseudonymised, to improve its tools (simulator, SBG
Home). I can withdraw this consent at any time."): **only if you tick it**, each month received is
used, 90 days after receipt, for **postcode statistics** (monthly totals without name, published
from 10 households) and a **pseudonymised copy** of the month's curve. Without it, none of this.
Unticking it (here or in your account) erases the copies; totals already given, anonymous, can no
longer be traced.
Conditions (French): <https://analyse.sbg-energy.com/conditions/#home-assistant>.

To stop: untick sending, or **Disconnect my SBG Energy account** in the same step. From your
account you can also **disconnect Home Assistant** and **erase** what was sent. An installation
erased from your account is refused afterwards: the integration then **turns sending off** and
says so (notification, and in the Send step), without retrying every day. To resume, allow it
again from your account, then tick sending again.

The **Last send** diagnostic sensor shows the date of the last send.

## What is stored on your system

- `<config>/sbg_energy_export/mesures/mesures_15min_YYYY-MM.csv` (or `mesures_5min_…`): one file
  per (UTC) month, one line per period and one column per statistic. The current month is plain
  text; every **finished month is compressed** (`.csv.gz`); exports read both transparently.
  With the 5-minute option, months **older than 12 months are grouped into quarter-hours**
  (version 0.4.0); months older than the **retention period** (3 years by default) are deleted.
- **Only what is needed**: the Energy dashboard's grid, solar and battery sources, and the devices
  you chose. These files contain your sensors' IDs: they stay inside Home Assistant, like its own
  database; anonymisation applies at export time.
- A device **added** later is recorded from then on, and caught up over the ~10 days for which
  Home Assistant still holds its 5-minute statistics. A device **removed** is no longer recorded
  or exported; what was already recorded stays until the end of the retention period (fine
  history cannot be rebuilt, and a device unticked by mistake gets its past back).
- Space measured over one simulated year with 10 devices (`outils/mesurer_stockage.py`):
  **≈ 0.4 MB** at 15 minutes, **≈ 1 MB** at 5 minutes (up to ≈ 0.7 and 1.8 MB with meters finer
  than 1 Wh). Over **3 years** with the 5-minute option (`--trois-ans`): **2.84 MB** all at 5
  minutes, **1.74 MB** with grouping after 12 months (39 % less).
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
- `custom_components/sbg_energy_export/brand/`: local brand images (official SBG Energy logo;
  Home Assistant 2026.3 and later), `dark_*` variants for the dark theme; `docs/brands/`: the same,
  ready for a request to the `home-assistant/brands` repository (not submitted; useful while HACS
  does not show local images); `docs/icone/`: the README icon. All produced by
  `outils/icones_marque.py` from the website's SVG.
- Tests: `pytest` with `pytest-homeassistant-custom-component` (Linux or WSL; Home Assistant does
  not run on Windows), with a real in-memory SQLite recorder:

  ```
  pip install -r requirements_test.txt
  pytest
  ```

## Privacy and GDPR

- **By default nothing leaves your Home Assistant**: the export is a file you download and upload
  yourself wherever you want. The integration makes no outgoing network call until direct sending
  is turned on **and** your account connected.
- **What direct sending transmits**: only the content of the export (energy per period for grid,
  solar, battery, home and the chosen devices under a neutral name), your postcode, the
  distribution system operator if chosen, the home if chosen from the service's list, the "Improve
  SBG tools" choice, a random installation identifier and the
  integration version (`User-Agent` header). Never an entity name, device name, room,
  address or location.
- **Data controller, purposes, retention periods, rights (access, rectification, erasure,
  withdrawal of consent) and contact**: see the service conditions,
  <https://analyse.sbg-energy.com/conditions/#home-assistant>. You can erase your data and
  disconnect Home Assistant from your SBG Energy account.
- **On your system**: the files listed above stay in your configuration folder; they are part of
  your Home Assistant backups.

## Uninstalling

1. **Settings → Devices & services → SBG Energy Export → ⋮ → Delete**. If direct sending was
   connected, the integration withdraws its authorisation at SBG Energy (best effort: without a
   network the token is only forgotten and expires after 30 days unused; you can also disconnect
   Home Assistant from your account).
2. **HACS → SBG Energy Export → ⋮ → Remove** (or delete the
   `custom_components/sbg_energy_export` folder for a manual install), then restart Home Assistant.
3. **Local data** is not deleted automatically (it is your data). To remove everything, delete the
   `<config>/sbg_energy_export/` folder and the files `.storage/sbg_energy_export.collecteur` and
   `.storage/sbg_energy_export.envoi` (with Home Assistant stopped).
4. **Data already sent** (direct sending only): erase it from your SBG Energy account.

## Licence

[Apache-2.0](LICENSE) (see also [NOTICE](NOTICE)). The SBG Energy name and logo are not covered by the
licence (section 6): they identify the origin of the project.

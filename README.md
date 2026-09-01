# MTR Monitor

> [Leia isso em Português](./README.pt-BR.md)

This repository contains a Shell script that **monitors** a host’s connectivity using [mtr (My Traceroute)](https://github.com/traviscross/mtr) and stores the results in a [SQLite](https://www.sqlite.org/index.html) database. It is ideal for checking **internet connection quality** at regular intervals and **preserving** historical data in a simple way.

## Table of Contents

1. [Main Features](#main-features)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Usage](#usage)
5. [Viewing Data in SQLite](#viewing-data-in-sqlite)
6. [Dashboard](#dashboard)
7. [Scheduling with Crontab](#scheduling-with-crontab)
8. [Customizations](#customizations)
9. [License](#license)

---

## Main Features

- Runs `mtr` in non-interactive mode and saves the output to **CSV**.
- Stores the results in the `mtr_data.db` (**SQLite** database).
- Creates separate logs by **hostname**, each with a **timestamp** (date/time) in its filename.
- Easy to configure and extend for other monitoring goals.

---

## Requirements

- **Linux** (tested on Ubuntu, Debian, and similar distributions)
- **mtr** installed (version >= 0.85 recommended)
- **SQLite3** installed (version >= 3.0)

The script checks if `mtr` and `sqlite3` are installed. If not, it will notify you and exit.

---

## Installation

1. **Clone** this repository:
   ```bash
   git clone https://github.com/rcarvalhoxavier/mtr-log.git
   cd mtr-log
   ```
2. **(Optional) Make the script executable**:
   ```bash
   chmod +x monitor.sh
   ```
3. **Install** any missing dependencies:
   - **Ubuntu/Debian**:
     ```bash
     sudo apt-get update
     sudo apt-get install mtr sqlite3
     ```
   - **Fedora/CentOS**:
     ```bash
     sudo dnf install mtr sqlite
     ```
   - Or [install sqlite3 manually](https://www.sqlite.org/download.html) if you need a different version.

---

## Usage

To run the script manually:

```bash
./monitor.sh
```

What the script does:

1. **Checks** that MTR and SQLite3 are installed.
2. **Creates** the `mtr_data.db` database (if it does not exist) and the `mtr_data` table.
3. **Runs** MTR against a target (default is `8.8.8.8`) and generates a CSV file whose name includes the date/time.
4. **Imports** that CSV into the `mtr_data.db` database.

### File Structure

- **logs/YOUR_HOSTNAME**: a directory created for each machine (where `hostname` returns `YOUR_HOSTNAME`).
  - Inside it, CSV files are generated following the format `YYYYMMDD_HHMMSS-mtr.csv`. For example:
    ```
    logs/machine01/20250124_135500-mtr.csv
    logs/machine01/20250124_140000-mtr.csv
    ...
    ```
- **mtr_data.db**: a SQLite database containing the `mtr_data` table. By default, the script creates columns matching the **standard** output of `mtr -C`.

#### Columns (Example Layout)

Typical columns you may see in MTR CSV outputs:

1. **Mtr_Version** – The MTR version that produced the record.
2. **Start_Time** – The moment the test started, often a Unix Epoch timestamp (seconds since 1970-01-01) or another textual format.
3. **Status** – Indicates the test state or result, such as “OK” or other codes.
4. **Host** – The destination host or IP for the hop.
5. **Hop** – The hop number in the route (starting from 1).
6. **Ip** – The address that answered at this hop, either an IP or a reverse hostname (`_gateway`, `100.70.0.1`, `dns.google`). MTR writes `???` when the hop did not answer, which the import converts to `NULL`. This is the column every path-segment classification is built on — `v_hop` reads it to decide whether a hop is `lan`, `cgnat`, `transito` or `desconhecido` — so do not drop it when adjusting the schema.
7. **Loss%** – Percentage of packet loss.
8. **Snt** – Number of packets sent.
9. **Drops** – Count of dropped packets. In the raw MTR CSV this column has **no header text** (a blank field between `Snt` and `Last`); older versions of this README did not document it at all. In the typed `mtr_data` table (see `scripts/schema.sql`) it is stored as the `drops` column.
10. **Last** – Latency of the last packet (ms).
11. **Avg** – Average latency (ms).
12. **Best** – Lowest (best) latency observed (ms).
13. **Wrst** – Highest (worst) latency observed (ms).
14. **StDev** – Standard deviation of the latency (ms).

If your version of MTR produces additional columns (e.g., `Mtr_Version`, `Start_Time`, `Status`, `Hop`, etc.), make sure to update the schema definition in `scripts/schema.sql` to match your actual CSV format — that file is the single source of truth for the database structure, applied by both `monitor.sh` and `scripts/migrate.sh`.

---

## Viewing Data in SQLite

If you want to **view** the data in the database, use:

```bash
sqlite3 mtr_data.db

-- Example query:
SELECT * FROM mtr_data LIMIT 10;
```

This displays the first 10 rows. You can also use tools like [DB Browser for SQLite](https://sqlitebrowser.org/) for a more user-friendly interface.

---

## Dashboard

Generate a static HTML report from the collected data with:

```bash
python3 scripts/dashboard.py
```

This writes `dashboard.html` in the repository root. It has no dependencies beyond the Python 3.12 standard library — no packages to install, and no external assets: the file is self-contained (no `http`/`https` references, no `<script>`, no `@import`) and can be opened directly in a browser or shared as-is.

The report has three panels, each answering one question:

1. **De quem é a culpa (Who's to blame)** – Does the degradation originate on my own network or outside it?
2. **Está pior que o normal (Is it worse than usual)** – Is the recent time window worse than the historical baseline?
3. **A rota está instável (Is the route unstable)** – Is the path to the destination changing or breaking?

**A note on packet loss:** loss reported at an intermediate hop that does **not** propagate to the destination hop is an ICMP artifact — many routers deprioritize or rate-limit their own ICMP TTL-exceeded replies, which shows up as "loss" at that hop without any real impact on connectivity. The dashboard (and the underlying `v_loss` view) reports this explicitly as an **artifact**, separate from **real** loss (where the destination hop itself shows loss). Only real loss is counted as degradation.

**Migrating databases created before this version:** `mtr_data.db` files created before the typed schema was introduced use an all-`TEXT` legacy layout. Bring them up to date with:

```bash
bash scripts/migrate.sh
```

The script is idempotent: on an already-migrated database it only re-applies the views and exits, **without** creating a backup — there is nothing to back up, because nothing is modified. A timestamped backup (`mtr_data.db.bak-YYYYMMDD_HHMMSS`) is created only on the path that actually migrates data, right before the old table is renamed.

Exit codes are worth checking when calling it from a script:

| Code | Meaning |
|---|---|
| `0` | Migration completed, or the database was already migrated (no-op). |
| `1` | Nothing was changed: database or schema file not found, or the row counts of source and destination diverged. In the divergence case the `mtr_legacy` table and the backup are both preserved. |
| `2` | **The database is half-migrated.** An `mtr_legacy` table left over from a previously aborted run was found, so this run refused to touch anything. Resolve it by hand — restore the backup, or drop `mtr_legacy` if `mtr_data` is already correct — before running again. |

---

## Scheduling with Crontab

To run the script automatically every 5 minutes:

1. Edit the **crontab** for your user:
   ```bash
   crontab -e
   ```
2. Add a line (adjusting the full path to the script):
   ```bash
   */5 * * * * /home/username/mtr-log/monitor.sh
   ```
3. Save the file. This will execute the script every 5 minutes, creating a new CSV file (with date/time in the name) and importing it into `mtr_data.db`.

> **Note**: When run by cron, the working directory may differ. In the script, we use `SCRIPT_DIR="$(dirname "$(realpath "$0")")"` to ensure logs and the database are created in the script’s own directory.

> **Note for tests and experiments**: `monitor.sh` writes to `$MTR_DB` when that variable is set, falling back to the database next to the script. Always export `MTR_DB` pointing at a throwaway file before sourcing the script — running the test suite or any manual import against the live `mtr_data.db` injects fabricated rows into a database that cron is appending to every 5 minutes.

---

## Customizations

- **Change the target**: In `monitor.sh`, look for the variable `ALVO="8.8.8.8"` and replace it with your desired IP or hostname.
- **Number of packets (cycles)**: The script runs `mtr -r -C "$ALVO"` and passes **no** `-c` option, so MTR's own default applies — 10 cycles per run, which is why `Snt` is 10 in 415,777 of the 415,797 collected rows. Add `-c N` to that command (e.g. `mtr -r -C -c 20 "$ALVO"`) if you want more samples per run.
- **Table structure**: If you wish to store additional data (timestamp, hop, IP, etc.), edit the function creating the table and adjust the CSV generation (by using `-o "col1 col2..."` with MTR or a custom build).
- **Run on IPv6**: Add the `-6` option to the MTR command if your system supports IPv6.

---

## License

This project is licensed under the [MIT License](LICENSE). Feel free to use, modify, and distribute it as needed.

---

**Questions or suggestions?**
Open an [issue](https://github.com/rcarvalhoxavier/mtr-log/issues) in this repository or submit a Pull Request!
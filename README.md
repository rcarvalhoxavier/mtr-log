Below is an **English** version of your README, keeping the same structure while making the text clear and concise.

---

# MTR Monitor

This repository contains a Shell script that **monitors** a host’s connectivity using [mtr (My Traceroute)](https://github.com/traviscross/mtr) and stores the results in a [SQLite](https://www.sqlite.org/index.html) database. It is ideal for checking **internet connection quality** at regular intervals and **preserving** historical data in a simple way.

## Table of Contents

1. [Main Features](#main-features)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Usage](#usage)
5. [Viewing Data in SQLite](#viewing-data-in-sqlite)
6. [Scheduling with Crontab](#scheduling-with-crontab)
7. [Customizations](#customizations)
8. [License](#license)

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
6. **Loss%** – Percentage of packet loss.
7. **Snt** – Number of packets sent.
8. **Last** – Latency of the last packet (ms).
9. **Avg** – Average latency (ms).
10. **Best** – Lowest (best) latency observed (ms).
11. **Wrst** – Highest (worst) latency observed (ms).
12. **StDev** – Standard deviation of the latency (ms).

If your version of MTR produces additional columns (e.g., `Mtr_Version`, `Start_Time`, `Status`, `Hop`, etc.), make sure to update the **CREATE TABLE** statement in `monitor.sh` to match your actual CSV format.

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

---

## Customizations

- **Change the target**: In `monitor.sh`, look for the variable `ALVO="8.8.8.8"` and replace it with your desired IP or hostname.
- **Number of packets (cycles)**: Modify the `-c 5` option to a different value (e.g., `-c 10`) if you want more samples per run.
- **Table structure**: If you wish to store additional data (timestamp, hop, IP, etc.), edit the function creating the table and adjust the CSV generation (by using `-o "col1 col2..."` with MTR or a custom build).
- **Run on IPv6**: Add the `-6` option to the MTR command if your system supports IPv6.

---

## License

This project is licensed under the [MIT License](LICENSE). Feel free to use, modify, and distribute it as needed.

---

**Questions or suggestions?**
Open an [issue](https://github.com/rcarvalhoxavier/mtr-log/issues) in this repository or submit a Pull Request!
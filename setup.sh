#!/usr/bin/env bash

sqlite3 mtr_data.db <<EOF
CREATE TABLE IF NOT EXISTS mtr_data (
    Mtr_Version TEXT,
    Start_Time TEXT,
    Status TEXT,
    Host TEXT,
    Hop TEXT,
    Ip TEXT,
    Loss TEXT,
    Snt TEXT,
    Empty TEXT,
    Empty2 TEXT,
    Last TEXT,
    Avg TEXT,
    Best TEXT,
    Wrst TEXT,
    StDev TEXT
);
.quit
EOF

sqlite3 mtr_data.db <<EOF
.import --csv --skip 1 resultado.csv mtr_data
.quit
EOF
#!/bin/bash

# Resolvido no topo, antes de qualquer função: setup_database rodava antes de
# monitor() e usava caminho relativo ao CWD, então pelo cron a tabela nascia
# num banco e os dados iam para outro.
SCRIPT_DIR="$(dirname "$(realpath "${BASH_SOURCE[0]}")")"
DB="$SCRIPT_DIR/mtr_data.db"
SCHEMA="$SCRIPT_DIR/scripts/schema.sql"

# Alvo externo a ser testado.
ALVO="8.8.8.8"

function check_dependencies() {
    if ! command -v mtr &> /dev/null; then
        echo "MTR não está instalado. Por favor, instale-o antes de continuar. https://github.com/traviscross/mtr"
        exit 1
    fi

    if ! command -v sqlite3 &> /dev/null; then
        echo "SQLite3 não está instalado. Por favor, instale-o antes de continuar. https://www.sqlite.org/download.html"
        exit 1
    fi
}

function setup_database() {
    sqlite3 "$DB" < "$SCHEMA"
}

function import_data() {
    # O mtr falha de vez em quando e deixa um arquivo de zero byte.
    if [ ! -s "$LOG_FILE" ]; then
        echo "sem saída do mtr em $LOG_FILE; nada a importar" >&2
        return 0
    fi

    # O .import exige uma tabela com a forma exata do CSV, daí a staging.
    # O INSERT OR IGNORE contra a chave primária torna o import idempotente.
    sqlite3 "$DB" <<EOF
DELETE FROM mtr_raw;
.import --csv --skip 1 "$LOG_FILE" mtr_raw
INSERT OR IGNORE INTO mtr_data
    (ts, host, hop, ip, loss, snt, drops, last, avg, best, wrst, stdev, version, status)
SELECT
    CAST(Start_Time AS INTEGER),
    Host,
    CAST(Hop AS INTEGER),
    NULLIF(Ip, '???'),
    CAST(Loss AS REAL),
    CAST(Snt AS INTEGER),
    CAST(Drops AS INTEGER),
    CAST(Last AS REAL),
    CAST(Avg AS REAL),
    CAST(Best AS REAL),
    CAST(Wrst AS REAL),
    CAST(StDev AS REAL),
    Mtr_Version,
    Status
FROM mtr_raw;
DELETE FROM mtr_raw;
EOF
}

function monitor() {
    local HOSTNAME_LOCAL
    HOSTNAME_LOCAL=$(hostname)

    local LOG_DIR="$SCRIPT_DIR/logs/$HOSTNAME_LOCAL"
    mkdir -p "$LOG_DIR"

    local TIMESTAMP
    TIMESTAMP=$(date +'%Y%m%d_%H%M%S')
    LOG_FILE="$LOG_DIR/${TIMESTAMP}-mtr.csv"

    mtr -r -C "$ALVO" > "$LOG_FILE"
}

function main() {
    check_dependencies
    setup_database
    monitor
    import_data
}

# Só executa quando chamado diretamente; permite `source` nos testes.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main
fi

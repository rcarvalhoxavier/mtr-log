#!/bin/bash

function check_dependencies() {
    # Verifica se o MTR está instalado
    if ! command -v mtr &> /dev/null; then
        echo "MTR não está instalado. Por favor, instale-o antes de continuar. https://github.com/traviscross/mtr"
        exit 1
    fi

    # Verifica se o SQLite3 está instalado
    if ! command -v sqlite3 &> /dev/null; then
        echo "SQLite3 não está instalado. Por favor, instale-o antes de continuar. https://www.sqlite.org/download.html"
        exit 1
    fi
}

function setup_database() {
    # Cria o banco de dados SQLite3 e a tabela
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
    Last TEXT,
    Avg TEXT,
    Best TEXT,
    Wrst TEXT,
    StDev TEXT
);
.quit
EOF
}

function import_data() {
# Importa os dados do arquivo CSV para o banco de dados
sqlite3 mtr_data.db <<EOF
.import --csv --skip 1 "$LOG_FILE" mtr_data
.quit
EOF
}


function monitor() {

# Define o alvo externo que você quer testar
local ALVO="8.8.8.8"

# Captura o nome do host atual
local HOSTNAME_LOCAL=$(hostname)

# Define diretório de logs
local LOG_DIR="$PWD/logs/$HOSTNAME_LOCAL"
mkdir -p "$LOG_DIR"

# Define o nome do arquivo de log (com a data do dia)
local TIMESTAMP
TIMESTAMP=$(date +'%Y%m%d_%H%M%S')
LOG_FILE="$LOG_DIR/${TIMESTAMP}-mtr.csv"

# Executa MTR para o alvo externo e **não** imprime cabeçalhos adicionais
mtr -r -C "$ALVO" > "$LOG_FILE"
}

function main() {
    check_dependencies
    setup_database
    monitor
    import_data
}

main
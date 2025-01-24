#!/bin/bash

# Define o alvo externo que você quer testar
ALVO="8.8.8.8"

# Captura o nome do host atual
HOSTNAME_LOCAL=$(hostname)

# Define diretório de logs
LOG_DIR="$PWD/logs/$HOSTNAME_LOCAL"
mkdir -p "$LOG_DIR"

# Define o nome do arquivo de log (com a data do dia)
LOG_FILE="$LOG_DIR/$(date +'%Y%m%d')-mtr.log"

# Executa MTR para o alvo externo e **não** imprime cabeçalhos adicionais
mtr -r -c 5 "$ALVO" >> "$LOG_FILE"

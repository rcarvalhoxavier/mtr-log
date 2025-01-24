#!/usr/bin/env bash

LOG_FILE="${1:-mtr.log}"  # se não passar parâmetro, usa 'mtr.log'

# Expressões Regulares
# Pega a linha do tipo: ----- MTR EXTERNO: 2025-01-23 21:47:48 -----
# Captura em dois grupos:
#  - (EXTERNO ou LOCAL)
#  - data/hora no formato YYYY-MM-DD HH:MM:SS
re_date='^----- MTR (EXTERNO|LOCAL): ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) -----$'

# Pega a linha do tipo:
#   2.|-- 100.68.0.1                20.0%     5   71.6  68.7  64.0  71.6   3.3
# Capturando 9 grupos:
# 1) hop      (ex: "2")
# 2) host     (ex: "100.68.0.1")
# 3) loss     (ex: "20.0")
# 4) snt      (ex: "5")
# 5) last     (ex: "71.6")
# 6) avg      (ex: "68.7")
# 7) best     (ex: "64.0")
# 8) wrst     (ex: "71.6")
# 9) stdev    (ex: "3.3")
re_hop='^[[:space:]]+([0-9]+)\.\|--[[:space:]]+([^[:space:]]+)[[:space:]]+([0-9.]+)%[[:space:]]+([0-9]+)[[:space:]]+([0-9.]+)[[:space:]]+([0-9.]+)[[:space:]]+([0-9.]+)[[:space:]]+([0-9.]+)[[:space:]]+([0-9.]+)$'

current_date=""
current_type=""

# Cabeçalho (opcional, caso queira CSV com colunas)
echo "Data,Tipo,Hop,Host,Loss,Snt,Last,Avg,Best,Wrst,StDev"

while IFS= read -r line
do
    # Testa se a linha casa com a data MTR EXTERNO|LOCAL
    if [[ "$line" =~ $re_date ]]; then
        current_type="${BASH_REMATCH[1]}"
        current_date="${BASH_REMATCH[2]}"
        continue
    fi

    # Testa se a linha casa com o formato de hop
    if [[ "$line" =~ $re_hop ]]; then
        hop="${BASH_REMATCH[1]}"
        host="${BASH_REMATCH[2]}"
        loss="${BASH_REMATCH[3]}"
        snt="${BASH_REMATCH[4]}"
        last="${BASH_REMATCH[5]}"
        avg="${BASH_REMATCH[6]}"
        best="${BASH_REMATCH[7]}"
        wrst="${BASH_REMATCH[8]}"
        stdev="${BASH_REMATCH[9]}"

        # Imprime em CSV
        echo "${current_date},${current_type},${hop},${host},${loss},${snt},${last},${avg},${best},${wrst},${stdev}"
    fi
done < "$LOG_FILE"

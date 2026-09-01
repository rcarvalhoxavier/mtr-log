#!/bin/bash
# Migra o banco legado (todas as colunas TEXT) para o schema tipado.
# Idempotente: reexecutar num banco já migrado não faz nada.
# PRÉ-CONDIÇÃO: o cron responsável pela escrita (monitor.sh) deve estar pausado antes da migração.
#               A Task 7 do plano é responsável por fazer isso automaticamente.
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
DB="${1:-$SCRIPT_DIR/../mtr_data.db}"
SCHEMA="$SCRIPT_DIR/schema.sql"

if [ ! -f "$DB" ]; then
    echo "banco não encontrado: $DB" >&2
    exit 1
fi

if [ ! -f "$SCHEMA" ]; then
    echo "schema não encontrado: $SCHEMA" >&2
    exit 1
fi

# Detectar estado inconsistente: se mtr_legacy existe, é um aborto anterior não resolvido.
# Banco já migrado tem 'ts' mas NÃO tem 'mtr_legacy'.
LEGACY_EXISTS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='mtr_legacy';")
if [ "$LEGACY_EXISTS" -eq 1 ]; then
    echo "ERRO: banco em estado inconsistente. A tabela mtr_legacy existe." >&2
    echo "Isto acontece quando a migração anterior foi abortada." >&2
    echo "Decisões possíveis:" >&2
    echo "  1. Restaurar do backup (.bak-YYYYMMDD_HHMMSS) e retentar" >&2
    echo "  2. Se os dados em mtr_data estão OK, remover mtr_legacy manualmente:" >&2
    echo "     sqlite3 $DB \"DROP TABLE mtr_legacy;\"" >&2
    echo "     E reexecutar este script (será no-op)." >&2
    exit 2
fi

# Já migrado? A coluna 'ts' só existe no schema novo.
if [ "$(sqlite3 "$DB" "SELECT COUNT(*) FROM pragma_table_info('mtr_data') WHERE name='ts';")" -eq 1 ]; then
    echo "banco já está no schema tipado; nada a fazer"
    sqlite3 "$DB" < "$SCHEMA"   # garante que as views existem
    exit 0
fi

BACKUP="$DB.bak-$(date +%Y%m%d_%H%M%S)"
cp "$DB" "$BACKUP"
echo "backup em $BACKUP"

# Contar ORIGEM com o mesmo CAST que será aplicado no destino para evitar colisões de tipo.
# Ex: Hop='2' e Hop='02' são distintos em TEXT mas colapsam após CAST(Hop AS INTEGER).
ORIGEM=$(sqlite3 "$DB" "SELECT COUNT(*) FROM (SELECT DISTINCT CAST(Start_Time AS INTEGER), Host, CAST(Hop AS INTEGER) FROM mtr_data);")
echo "linhas distintas na origem (pós-CAST): $ORIGEM"

# As views saem antes do ALTER. O monitor.sh aplica schema.sql a cada coleta, então
# num banco ainda legado elas já existem apontando para colunas que não existem — o
# SQLite não valida as colunas de uma view na criação. O ALTER TABLE tenta reescrever
# as referências dentro delas e aborta com "no such column: ts". O schema.sql, aplicado
# logo abaixo, recria as três sobre a tabela nova.
sqlite3 "$DB" <<SQL
DROP VIEW IF EXISTS v_loss;
DROP VIEW IF EXISTS v_run;
DROP VIEW IF EXISTS v_hop;
ALTER TABLE mtr_data RENAME TO mtr_legacy;
SQL

sqlite3 "$DB" < "$SCHEMA"

sqlite3 "$DB" <<'SQL'
INSERT OR IGNORE INTO mtr_data
    (ts, host, hop, ip, loss, snt, drops, last, avg, best, wrst, stdev, version, status)
SELECT
    CAST(Start_Time AS INTEGER),
    Host,
    CAST(Hop AS INTEGER),
    NULLIF(Ip, '???'),
    CAST(Loss AS REAL),
    CAST(Snt AS INTEGER),
    CAST(Empty AS INTEGER),
    CAST(Last AS REAL),
    CAST(Avg AS REAL),
    CAST(Best AS REAL),
    CAST(Wrst AS REAL),
    CAST(StDev AS REAL),
    Mtr_Version,
    Status
FROM mtr_legacy;
SQL

DESTINO=$(sqlite3 "$DB" "SELECT COUNT(*) FROM mtr_data;")
echo "linhas no destino: $DESTINO"

if [ "$ORIGEM" -ne "$DESTINO" ]; then
    echo "ABORTADO: origem ($ORIGEM) e destino ($DESTINO) divergem." >&2
    echo "A tabela mtr_legacy foi preservada e o backup está em $BACKUP" >&2
    exit 1
fi

sqlite3 "$DB" "DROP TABLE mtr_legacy;"
sqlite3 "$DB" "VACUUM;"
echo "migração concluída: $DESTINO linhas"

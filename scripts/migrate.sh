#!/bin/bash
# Migra o banco legado (todas as colunas TEXT) para o schema tipado.
# Idempotente: reexecutar num banco já migrado não faz nada.
# PRÉ-CONDIÇÃO: o cron responsável pela escrita (monitor.sh) deve estar pausado antes da migração.
#
# Uso: migrate.sh [caminho_do_banco] [--aceitar-perda]
set -euo pipefail

SCRIPT_DIR="$(dirname "$(realpath "$0")")"
SCHEMA="$SCRIPT_DIR/schema.sql"

# --aceitar-perda prossegue quando linhas do banco legado não cabem no schema tipado, e
# retoma uma migração que abortou no meio. Nunca é o padrão: descartar dado em silêncio
# é exatamente o que o aborto existe para impedir.
ACEITAR_PERDA=0
DB=""
for arg in "$@"; do
    if [ "$arg" = "--aceitar-perda" ]; then
        ACEITAR_PERDA=1
    else
        DB="$arg"
    fi
done
DB="${DB:-$SCRIPT_DIR/../mtr_data.db}"

# Linhas do legado cuja chave não sobrevive ao schema tipado. `ts`, `host` e `hop` são
# NOT NULL, e o INSERT OR IGNORE engole a violação sem avisar.
SEM_CHAVE_WHERE="CAST(Start_Time AS INTEGER) IS NULL OR Host IS NULL OR CAST(Hop AS INTEGER) IS NULL"

contar_sem_chave() {
    sqlite3 "$DB" "SELECT COUNT(*) FROM mtr_legacy WHERE $SEM_CHAVE_WHERE;"
}

promover() {
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
}

finalizar() {
    sqlite3 "$DB" "DROP TABLE mtr_legacy;"
    sqlite3 "$DB" "VACUUM;"
    echo "migração concluída: $(sqlite3 "$DB" "SELECT COUNT(*) FROM mtr_data;") linhas"
}

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

if [ "$LEGACY_EXISTS" -eq 1 ] && [ "$ACEITAR_PERDA" -eq 1 ]; then
    echo "estado inconsistente aceito por --aceitar-perda: retomando a migração"
    promover   # idempotente; só preenche o que ficou faltando
    echo "linhas sem chave utilizável, descartadas: $(contar_sem_chave)"
    finalizar
    exit 0
fi

if [ "$LEGACY_EXISTS" -eq 1 ]; then
    echo "ERRO: banco em estado inconsistente. A tabela mtr_legacy existe." >&2
    echo "Isto acontece quando a migração anterior foi abortada." >&2
    echo "Decisões possíveis:" >&2
    echo "  1. Restaurar do backup (.bak-YYYYMMDD_HHMMSS) e retentar" >&2
    echo "  2. Retomar descartando o que não couber: reexecute com --aceitar-perda" >&2
    echo "  3. Se os dados em mtr_data já estão OK, remover mtr_legacy manualmente:" >&2
    echo "     sqlite3 $DB \"DROP TABLE mtr_legacy;\"" >&2
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

promover

DESTINO=$(sqlite3 "$DB" "SELECT COUNT(*) FROM mtr_data;")
echo "linhas no destino: $DESTINO"

if [ "$ORIGEM" -ne "$DESTINO" ]; then
    SEM_CHAVE=$(contar_sem_chave)
    if [ "$ACEITAR_PERDA" -eq 0 ]; then
        echo "ABORTADO: origem ($ORIGEM) e destino ($DESTINO) divergem." >&2
        echo "$SEM_CHAVE linhas têm Start_Time, Host ou Hop nulos e violam NOT NULL no schema tipado." >&2
        echo "Para ver quais são:" >&2
        echo "  sqlite3 $DB \"SELECT Start_Time, Host, Hop, Ip, Status FROM mtr_legacy WHERE $SEM_CHAVE_WHERE;\"" >&2
        echo "Para prosseguir descartando-as, reexecute com --aceitar-perda." >&2
        echo "A tabela mtr_legacy foi preservada e o backup está em $BACKUP" >&2
        exit 1
    fi
    echo "AVISO: $((ORIGEM - DESTINO)) linhas descartadas, aceito por --aceitar-perda"
    echo "  destas, $SEM_CHAVE têm Start_Time, Host ou Hop nulos"
fi

finalizar

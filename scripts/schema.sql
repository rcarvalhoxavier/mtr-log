-- Schema do mtr-log. Fonte única, consumida por monitor.sh, migrate.sh e testes.
-- Aplicável repetidamente sem efeito colateral.

-- Tabela principal. Tipos corretos: a versão anterior guardava tudo como TEXT,
-- o que obrigava CAST em toda query e impedia o uso de qualquer índice.
CREATE TABLE IF NOT EXISTS mtr_data (
    ts      INTEGER NOT NULL,   -- Start_Time do mtr, em epoch
    host    TEXT    NOT NULL,   -- alvo do teste
    hop     INTEGER NOT NULL,
    ip      TEXT,               -- NULL onde o mtr escreveu '???'
    loss    REAL,               -- Loss%
    snt     INTEGER,
    drops   INTEGER,            -- pacotes perdidos; era a coluna chamada 'Empty'
    last    REAL,
    avg     REAL,
    best    REAL,
    wrst    REAL,
    stdev   REAL,
    version TEXT,
    status  TEXT,
    PRIMARY KEY (ts, host, hop)
) WITHOUT ROWID;

-- Staging do import. Espelha o CSV do mtr: 14 campos, todos texto.
-- O .import do sqlite3 exige uma tabela com a forma exata do arquivo.
CREATE TABLE IF NOT EXISTS mtr_raw (
    Mtr_Version TEXT, Start_Time TEXT, Status TEXT, Host TEXT,
    Hop TEXT, Ip TEXT, Loss TEXT, Snt TEXT, Drops TEXT,
    Last TEXT, Avg TEXT, Best TEXT, Wrst TEXT, StDev TEXT
);

-- v_hop: todos os hops, com o segmento do caminho a que pertencem.
-- A ordem dos WHEN é a regra: o primeiro que casar define o segmento.
-- Atenção: 'não é IP' NÃO implica rede local. dns.google, sodobrasil.net.br e
-- ix.br são hostnames públicos e pertencem a transito.
DROP VIEW IF EXISTS v_hop;
CREATE VIEW v_hop AS
SELECT
    m.*,
    CASE
        WHEN m.ip IS NULL                                        THEN 'desconhecido'
        WHEN m.hop = 1                                           THEN 'lan'
        WHEN m.ip LIKE '192.168.%'                               THEN 'lan'
        WHEN m.ip LIKE '10.%'                                    THEN 'lan'
        WHEN m.ip GLOB '172.1[6-9].*'
          OR m.ip GLOB '172.2[0-9].*'
          OR m.ip GLOB '172.3[0-1].*'                            THEN 'lan'
        WHEN m.ip NOT LIKE '%.%'                                 THEN 'lan'
        WHEN m.ip LIKE '%.home.arpa'
          OR m.ip LIKE '%.lan'
          OR m.ip LIKE '%.local'                                 THEN 'lan'
        -- 100.64.0.0/10, faixa de CGNAT: segundo octeto de 64 a 127.
        WHEN m.ip GLOB '100.6[4-9].*'
          OR m.ip GLOB '100.[7-9][0-9].*'
          OR m.ip GLOB '100.1[0-1][0-9].*'
          OR m.ip GLOB '100.12[0-7].*'                           THEN 'cgnat'
        ELSE 'transito'
    END AS segmento
FROM mtr_data m;

-- v_run: uma linha por execução, com os dados do hop de destino.
-- É a única fonte confiável de latência e perda reais (spec §2.3).
DROP VIEW IF EXISTS v_run;
CREATE VIEW v_run AS
SELECT
    m.ts, m.host, m.hop AS hops, m.ip AS dest_ip,
    m.loss, m.drops, m.snt, m.last, m.avg, m.best, m.wrst, m.stdev
FROM mtr_data m
JOIN (
    SELECT ts, host, MAX(hop) AS ultimo FROM mtr_data GROUP BY ts, host
) d ON d.ts = m.ts AND d.host = m.host AND d.ultimo = m.hop;

-- v_loss: perda por execução, já separando degradação real de artefato de ICMP.
-- Sem essa distinção, 17.646 execuções de perda inexistente poluem o resultado.
DROP VIEW IF EXISTS v_loss;
CREATE VIEW v_loss AS
SELECT
    r.ts,
    r.host,
    r.hops,
    r.loss AS loss_destino,
    r.drops,
    COALESCE((
        SELECT MAX(h.loss) FROM mtr_data h
        WHERE h.ts = r.ts AND h.host = r.host AND h.hop < r.hops
    ), 0) AS loss_intermediaria,
    CASE
        WHEN r.loss > 0 THEN 'real'
        WHEN COALESCE((
            SELECT MAX(h.loss) FROM mtr_data h
            WHERE h.ts = r.ts AND h.host = r.host AND h.hop < r.hops
        ), 0) > 0 THEN 'artefato'
        ELSE 'sem_perda'
    END AS classificacao
FROM v_run r;

"""Consultas ao banco e estatística. Não emite HTML."""
import math
import sqlite3

# Janela considerada "recente" no Painel 2.
DIAS_JANELA_RECENTE = 7
# Extensão da série diária mostrada no Painel 2.
DIAS_SERIE_RECENTE = 30

SEGUNDOS_POR_DIA = 86400


def conectar(caminho):
    """Conexão somente leitura: o dashboard nunca escreve no banco."""
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def percentil(valores, p):
    """Percentil pelo método do rank mais próximo. None se a lista for vazia."""
    if not valores:
        return None
    ordenados = sorted(valores)
    posicao = math.ceil(p / 100 * len(ordenados))
    return ordenados[max(posicao - 1, 0)]


def ultimo_ts(con):
    return con.execute("SELECT MAX(ts) AS t FROM v_run").fetchone()["t"]


def latencia_diaria(con, desde_ts=None):
    """p50 e p95 da latência do destino, por dia."""
    sql = (
        "SELECT date(ts,'unixepoch','localtime') AS dia, avg"
        " FROM v_run WHERE avg IS NOT NULL"
    )
    parametros = []
    if desde_ts is not None:
        sql += " AND ts >= ?"
        parametros.append(desde_ts)

    por_dia = {}
    for linha in con.execute(sql, parametros):
        por_dia.setdefault(linha["dia"], []).append(linha["avg"])

    return [
        {
            "dia": dia,
            "p50": percentil(valores, 50),
            "p95": percentil(valores, 95),
            "amostras": len(valores),
        }
        for dia, valores in sorted(por_dia.items())
    ]


def latencia_por_segmento(con):
    """Mediana de `best` por segmento, mais a do destino.

    Usa `best` e não `avg` porque roteadores intermediários despriorizam ICMP:
    o mínimo é muito menos poluído por esse efeito (spec §2.3).
    """
    por_segmento = {}
    consulta = (
        "SELECT segmento, best FROM v_hop"
        " WHERE best IS NOT NULL AND segmento != 'desconhecido'"
    )
    for linha in con.execute(consulta):
        por_segmento.setdefault(linha["segmento"], []).append(linha["best"])

    resultado = []
    for segmento in ("lan", "cgnat", "transito"):
        valores = por_segmento.get(segmento)
        if valores:
            resultado.append({
                "segmento": segmento,
                "p50": percentil(valores, 50),
                "amostras": len(valores),
            })

    destino = [
        linha["best"]
        for linha in con.execute("SELECT best FROM v_run WHERE best IS NOT NULL")
    ]
    if destino:
        resultado.append({
            "segmento": "destino",
            "p50": percentil(destino, 50),
            "amostras": len(destino),
        })
    return resultado


def contagem_de_classificacao(con, desde_ts=None):
    sql = "SELECT classificacao, COUNT(*) AS n FROM v_loss"
    parametros = []
    if desde_ts is not None:
        sql += " WHERE ts >= ?"
        parametros.append(desde_ts)
    sql += " GROUP BY classificacao"
    return {linha["classificacao"]: linha["n"] for linha in con.execute(sql, parametros)}


def eventos_de_perda(con, limite=40):
    """Apenas perda que chegou ao destino. Artefato de ICMP não entra."""
    consulta = """
        SELECT datetime(ts,'unixepoch','localtime') AS quando,
               loss_destino, drops, hops, loss_intermediaria
        FROM v_loss
        WHERE classificacao = 'real'
        ORDER BY ts DESC
        LIMIT ?
    """
    return [dict(linha) for linha in con.execute(consulta, (limite,))]


def comparacao_baseline(con, dias_janela=DIAS_JANELA_RECENTE):
    """Janela recente contra o histórico completo.

    O baseline inclui a janela recente. Com 19 meses contra 7 dias a diluição é
    de ~0,1%, e a alternativa (excluir) tornaria o baseline móvel e menos
    comparável entre execuções do dashboard.
    """
    fim = ultimo_ts(con)
    if fim is None:
        return None

    corte = fim - dias_janela * SEGUNDOS_POR_DIA
    recentes = [
        linha["avg"]
        for linha in con.execute(
            "SELECT avg FROM v_run WHERE ts >= ? AND avg IS NOT NULL", (corte,)
        )
    ]
    historico = [
        linha["avg"]
        for linha in con.execute("SELECT avg FROM v_run WHERE avg IS NOT NULL")
    ]

    def taxa_de_perda(contagem):
        total = sum(contagem.values())
        return (contagem.get("real", 0) / total * 100) if total else None

    return {
        "dias_janela": dias_janela,
        "corte": corte,
        "recente": {
            "p50": percentil(recentes, 50),
            "p95": percentil(recentes, 95),
            "amostras": len(recentes),
            "taxa_perda": taxa_de_perda(contagem_de_classificacao(con, corte)),
        },
        "baseline": {
            "p50": percentil(historico, 50),
            "p95": percentil(historico, 95),
            "amostras": len(historico),
            "taxa_perda": taxa_de_perda(contagem_de_classificacao(con)),
        },
    }


def ips_por_hop_por_dia(con):
    consulta = """
        SELECT date(ts,'unixepoch','localtime') AS dia, hop, COUNT(DISTINCT ip) AS ips
        FROM mtr_data
        WHERE ip IS NOT NULL
        GROUP BY dia, hop
        ORDER BY dia, hop
    """
    return [dict(linha) for linha in con.execute(consulta)]


def desconhecidos_por_dia(con):
    consulta = """
        SELECT date(ts,'unixepoch','localtime') AS dia, COUNT(*) AS n
        FROM mtr_data
        WHERE ip IS NULL
        GROUP BY dia
        ORDER BY dia
    """
    return [dict(linha) for linha in con.execute(consulta)]


def trocas_de_rota(con, limite=40):
    """Quando o IP predominante de um hop mudou de um dia para o outro."""
    consulta = """
        SELECT dia, hop, ip FROM (
            SELECT date(ts,'unixepoch','localtime') AS dia, hop, ip,
                   ROW_NUMBER() OVER (
                       PARTITION BY date(ts,'unixepoch','localtime'), hop
                       ORDER BY COUNT(*) DESC, ip
                   ) AS posicao
            FROM mtr_data
            WHERE ip IS NOT NULL
            GROUP BY dia, hop, ip
        )
        WHERE posicao = 1
        ORDER BY hop, dia
    """
    anterior = {}
    trocas = []
    for linha in con.execute(consulta):
        hop = linha["hop"]
        if hop in anterior and anterior[hop] != linha["ip"]:
            trocas.append({
                "dia": linha["dia"],
                "hop": hop,
                "de": anterior[hop],
                "para": linha["ip"],
            })
        anterior[hop] = linha["ip"]
    # Ordenar por data (descendente) com hop como desempate, depois truncar as mais recentes
    trocas_ordenadas = sorted(trocas, key=lambda t: (t["dia"], t["hop"]), reverse=True)
    return trocas_ordenadas[:limite]

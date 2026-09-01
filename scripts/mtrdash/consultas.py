"""Consultas ao banco e estatística. Não emite HTML."""
import math
import sqlite3

# Janela considerada "recente" no Painel 2.
DIAS_JANELA_RECENTE = 7
# Extensão da série diária mostrada no Painel 2.
DIAS_SERIE_RECENTE = 30

SEGUNDOS_POR_DIA = 86400

# Piso de plausibilidade para um timestamp de coleta. Uma escrita de CSV interrompida
# desloca as colunas e o Start_Time acaba recebendo um fragmento de latência, virando
# poucos segundos após o epoch. São linhas de parsing quebrado, não medições, e
# apresentá-las como dado faria o dashboard anunciar coletas de 1969.
TS_MINIMO = 946684800  # 2000-01-01

# Quantas execuções a seção "Agora" detalha. Com coleta a cada 5 minutos, 5
# execuções cobrem ~25 minutos — a janela de "está acontecendo agora".
EXECUCOES_RECENTES = 5


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


def percentil_ponderado(pares, p):
    """Percentil sobre pares (valor, frequência), pelo mesmo método do rank mais
    próximo de `percentil`, sem materializar a lista expandida.

    Existe por custo: numa base real, os milhões de valores de `best` colapsam em
    poucos milhares de pares distintos, porque a coluna tem duas casas decimais.
    Agregar no SQL e transferir os pares evita construir milhões de objetos Python.
    """
    total = sum(frequencia for _, frequencia in pares)
    if not total:
        return None
    alvo = math.ceil(p / 100 * total)
    acumulado = 0
    for valor, frequencia in sorted(pares):
        acumulado += frequencia
        if acumulado >= alvo:
            return valor
    return max(pares)[0]


def ultimo_ts(con):
    return con.execute("SELECT MAX(ts) AS t FROM v_run").fetchone()["t"]


def latencia_diaria(con, desde_ts=None):
    """p50 e p95 da latência do destino, por dia.

    Só entram traces completas: numa execução truncada o último hop é o
    roteador local, e a latência dele não é latência até o destino. Sem esse
    filtro, 2025-11-30 — dia em que as 287 execuções pararam no gateway —
    aparecia como o dia mais rápido da série, com 1,24 ms.
    """
    sql = (
        "SELECT date(ts,'unixepoch','localtime') AS dia, avg"
        " FROM v_run WHERE avg IS NOT NULL AND completa = 1"
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

    Segmentos sem amostra nenhuma são omitidos: numa topologia em que o roteador do
    provedor não está em modo bridge, o CGNAT fica atrás do NAT dele e a faixa
    100.64.0.0/10 nunca aparece na trace.
    """
    por_segmento = {}
    consulta = (
        "SELECT segmento, best, COUNT(*) AS n FROM v_hop"
        " WHERE best IS NOT NULL AND segmento != 'desconhecido'"
        " GROUP BY segmento, best"
    )
    for linha in con.execute(consulta):
        por_segmento.setdefault(linha["segmento"], []).append((linha["best"], linha["n"]))

    resultado = []
    for segmento in ("lan", "provedor", "cgnat", "transito"):
        pares = por_segmento.get(segmento)
        if pares:
            resultado.append({
                "segmento": segmento,
                "p50": percentil_ponderado(pares, 50),
                "amostras": sum(n for _, n in pares),
            })

    # A barra "destino" só pode somar execuções que chegaram ao destino;
    # latência de gateway já tem sua própria barra, a de `lan`.
    destino = [
        (linha["best"], linha["n"])
        for linha in con.execute(
            "SELECT best, COUNT(*) AS n FROM v_run"
            " WHERE best IS NOT NULL AND completa = 1 GROUP BY best"
        )
    ]
    if destino:
        resultado.append({
            "segmento": "destino",
            "p50": percentil_ponderado(destino, 50),
            "amostras": sum(n for _, n in destino),
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

    # As duas janelas usam só traces completas, pelo mesmo motivo de
    # latencia_diaria: caso contrário o delta compara latência de destino de um
    # lado com latência de gateway do outro.
    corte = fim - dias_janela * SEGUNDOS_POR_DIA
    recentes = [
        linha["avg"]
        for linha in con.execute(
            "SELECT avg FROM v_run"
            " WHERE ts >= ? AND avg IS NOT NULL AND completa = 1",
            (corte,),
        )
    ]
    historico = [
        linha["avg"]
        for linha in con.execute(
            "SELECT avg FROM v_run WHERE avg IS NOT NULL AND completa = 1"
        )
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


def ultimas_execucoes(con, limite=EXECUCOES_RECENTES):
    """As execuções mais recentes, mais recente primeiro, com os hops de cada uma.

    Cada item traz o resumo da execução e uma lista `detalhe` com um dicionário por
    hop alcançado. O detalhe por hop é o ponto da consulta: sem ele não se distingue
    uma queda do provedor de um roteador local sobrecarregado.
    """
    resumos = con.execute(
        """
        SELECT r.ts, datetime(r.ts,'unixepoch','localtime') AS quando,
               r.hops, r.completa, r.loss, r.avg, l.classificacao
        FROM v_run r
        JOIN v_loss l ON l.ts = r.ts AND l.host = r.host
        WHERE r.ts > ?
        ORDER BY r.ts DESC
        LIMIT ?
        """,
        (TS_MINIMO, limite),
    ).fetchall()
    if not resumos:
        return []

    marcadores = ",".join("?" * len(resumos))
    detalhes = {}
    for linha in con.execute(
        "SELECT ts, hop, ip, loss, avg FROM mtr_data"
        f" WHERE ts IN ({marcadores}) ORDER BY ts DESC, hop",
        [r["ts"] for r in resumos],
    ):
        detalhes.setdefault(linha["ts"], []).append(dict(linha))

    return [
        {**dict(resumo), "detalhe": detalhes.get(resumo["ts"], [])}
        for resumo in resumos
    ]

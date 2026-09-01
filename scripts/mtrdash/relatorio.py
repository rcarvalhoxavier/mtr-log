"""Monta o HTML dos três painéis a partir de `consultas` e `graficos`."""
from html import escape

from . import consultas, graficos

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; padding: 32px 24px 64px; background: #f8fafc; color: #0f172a;
       font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 980px; margin: 0 auto; }
h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 19px; margin: 0 0 2px; }
h3 { font-size: 15px; margin: 26px 0 8px; color: #334155; }
.subtitulo { color: #475569; margin: 0 0 32px; }
.pergunta { color: #64748b; margin: 0 0 18px; font-size: 14px; }
section { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
          padding: 22px 24px; margin-bottom: 24px; }
.gr { width: 100%; height: auto; display: block; }
.grade { stroke: #e2e8f0; stroke-width: 1; }
.rotulo-y { fill: #64748b; font-size: 11px; text-anchor: end; }
.rotulo-x { fill: #64748b; font-size: 11px; text-anchor: middle; }
.valor-barra { fill: #0f172a; font-size: 12px; font-weight: 600; text-anchor: middle; }
.legenda { display: flex; gap: 16px; margin-top: 6px; font-size: 13px; color: #475569; }
.chave { display: inline-flex; align-items: center; gap: 6px; }
.chave i { width: 11px; height: 11px; border-radius: 2px; display: inline-block; }
table { border-collapse: collapse; width: 100%; font-size: 14px; margin-top: 6px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid #e2e8f0; }
th { color: #475569; font-weight: 600; font-size: 12px; text-transform: uppercase;
     letter-spacing: .04em; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.cartoes { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
           gap: 14px; margin-bottom: 8px; }
.cartao { border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 16px; }
.cartao .titulo { font-size: 12px; color: #64748b; text-transform: uppercase;
                  letter-spacing: .04em; }
.cartao .valor { font-size: 24px; font-weight: 650; font-variant-numeric: tabular-nums; }
.cartao .delta { font-size: 13px; }
.pior { color: #dc2626; }
.melhor { color: #0f766e; }
.nota { background: #f1f5f9; border-left: 3px solid #94a3b8; padding: 12px 14px;
        border-radius: 0 6px 6px 0; font-size: 14px; color: #334155; margin-top: 18px; }
.rodape-tabela { color: #64748b; font-size: 13px; margin: 8px 0 0; }
.vazio { color: #64748b; font-style: italic; }
footer { color: #64748b; font-size: 13px; text-align: center; }
"""


def _numero(valor, casas=2, sufixo=""):
    return "—" if valor is None else f"{valor:.{casas}f}{sufixo}"


def _tabela(cabecalhos, linhas):
    if not linhas:
        return graficos.VAZIO
    cabeca = "".join(f"<th>{escape(str(c))}</th>" for c in cabecalhos)
    corpo = "".join(
        "<tr>"
        + "".join(
            f'<td class="num">{escape(str(celula))}</td>'
            if isinstance(celula, (int, float))
            else f"<td>{escape(str(celula))}</td>"
            for celula in linha
        )
        + "</tr>"
        for linha in linhas
    )
    return f"<table><thead><tr>{cabeca}</tr></thead><tbody>{corpo}</tbody></table>"


def _rodape_tabela(mostrados, total, substantivo):
    """Diz quantas linhas a tabela mostra de quantas existem.

    Tanto `eventos_de_perda` quanto `trocas_de_rota` truncam em 40. Sem este
    rótulo a tabela se passa pela lista completa — a nota do Painel 1 chegava a
    afirmar que ela listava as 1205 execuções de perda real, sendo que tinha 40
    linhas.
    """
    if not mostrados:
        return ""
    return (
        f'<p class="rodape-tabela">Tabela: <strong>{mostrados}</strong> de '
        f"<strong>{total}</strong> {escape(substantivo)}, as mais recentes.</p>"
    )


def _serie_de_latencia(serie):
    return [
        {
            "nome": "mediana",
            "cor": graficos.CORES["p50"],
            "pontos": [(d["dia"], d["p50"]) for d in serie],
        },
        {
            "nome": "p95",
            "cor": graficos.CORES["p95"],
            "pontos": [(d["dia"], d["p95"]) for d in serie],
        },
    ]


def painel_culpado(con):
    grafico_latencia = graficos.grafico_de_linhas(
        _serie_de_latencia(consultas.latencia_diaria(con))
    )

    barras = graficos.grafico_de_barras([
        {
            "rotulo": s["segmento"],
            "valor": s["p50"],
            "cor": graficos.CORES.get(s["segmento"], graficos.CORES["neutro"]),
        }
        for s in consultas.latencia_por_segmento(con)
    ])

    contagem = consultas.contagem_de_classificacao(con)
    eventos = consultas.eventos_de_perda(con)
    tabela = _tabela(
        ["quando", "perda no destino", "pacotes perdidos", "hops"],
        [
            (e["quando"], _numero(e["loss_destino"], 2, "%"), e["drops"], e["hops"])
            for e in eventos
        ],
    )
    tabela += _rodape_tabela(
        len(eventos), contagem.get("real", 0), "execuções de perda real"
    )

    # Artefato e incompleta são coisas diferentes e nenhuma das duas é
    # degradação: a primeira é perda que não existiu, a segunda é uma medição
    # que nem chegou a ser sobre o destino. As duas são contadas e explicadas,
    # nunca somadas ao número de perda real.
    nota = (
        '<div class="nota">'
        f'<strong>{contagem.get("artefato", 0)}</strong> execuções '
        "registraram perda em hop intermediário que não chegou ao destino. Isso é "
        "limitação de resposta a ICMP no roteador, não pacote perdido, e por isso "
        "não entra na tabela acima.<br>"
        f'<strong>{contagem.get("incompleta", 0)}</strong> execuções '
        "não chegaram ao alvo: o mtr parou antes do destino, então o que foi medido "
        "é o caminho parcial e não a conexão até o destino. Elas também ficam fora "
        "da tabela e fora dos gráficos de latência — a latência do roteador local "
        "não é latência até o destino."
        "</div>"
    )

    return f"""<section>
<h2>De quem é a culpa</h2>
<p class="pergunta">A degradação nasce na minha rede ou fora dela?</p>
<h3>Latência até o destino, por dia</h3>
{grafico_latencia}
<h3>Latência mínima por segmento do caminho</h3>
{barras}
<h3>Eventos de perda real</h3>
{tabela}
{nota}
</section>"""


def painel_baseline(con):
    comparacao = consultas.comparacao_baseline(con)
    if comparacao is None:
        return (
            "<section><h2>Está pior que o normal</h2>"
            f"{graficos.VAZIO}</section>"
        )

    recente = comparacao["recente"]
    baseline = comparacao["baseline"]

    def cartao(titulo, atual, referencia, sufixo):
        if atual is None or referencia is None:
            return (
                f'<div class="cartao"><div class="titulo">{escape(titulo)}</div>'
                f'<div class="valor">—</div></div>'
            )
        delta = atual - referencia
        classe = "pior" if delta > 0 else "melhor"
        sinal = "+" if delta > 0 else ""
        return (
            f'<div class="cartao"><div class="titulo">{escape(titulo)}</div>'
            f'<div class="valor">{atual:.2f}{escape(sufixo)}</div>'
            f'<div class="delta {classe}">{sinal}{delta:.2f}{escape(sufixo)} '
            f"vs baseline {referencia:.2f}{escape(sufixo)}</div></div>"
        )

    cartoes = "".join([
        cartao("Latência mediana", recente["p50"], baseline["p50"], " ms"),
        cartao("Latência p95", recente["p95"], baseline["p95"], " ms"),
        cartao("Execuções com perda", recente["taxa_perda"], baseline["taxa_perda"], "%"),
    ])

    fim = consultas.ultimo_ts(con)
    desde = fim - consultas.DIAS_SERIE_RECENTE * consultas.SEGUNDOS_POR_DIA
    grafico = graficos.grafico_de_linhas(
        _serie_de_latencia(consultas.latencia_diaria(con, desde_ts=desde))
    )

    return f"""<section>
<h2>Está pior que o normal</h2>
<p class="pergunta">Os últimos {comparacao["dias_janela"]} dias
({recente["amostras"]} execuções) contra todo o histórico
({baseline["amostras"]} execuções).</p>
<div class="cartoes">{cartoes}</div>
<h3>Últimos {consultas.DIAS_SERIE_RECENTE} dias</h3>
{grafico}
</section>"""


def painel_rota(con):
    registros = consultas.ips_por_hop_por_dia(con)
    dias = sorted({r["dia"] for r in registros})
    por_hop = {}
    for r in registros:
        por_hop.setdefault(r["hop"], {})[r["dia"]] = r["ips"]

    paleta = [graficos.CORES[c] for c in ("lan", "cgnat", "transito", "destino", "p95")]
    series = []
    for i, hop in enumerate(sorted(por_hop)[:5]):
        valores = por_hop[hop]
        series.append({
            "nome": f"hop {hop}",
            "cor": paleta[i % len(paleta)],
            # Todas as séries compartilham o mesmo eixo de dias; dia sem medição
            # vira None e é omitido da linha.
            "pontos": [(dia, valores.get(dia)) for dia in dias],
        })
    grafico_ips = graficos.grafico_de_linhas(series, unidade=" IPs")

    desconhecidos = consultas.desconhecidos_por_dia(con)
    grafico_desconhecidos = graficos.grafico_de_linhas(
        [{
            "nome": "hops sem resposta",
            "cor": graficos.CORES["p95"],
            "pontos": [(d["dia"], d["n"]) for d in desconhecidos],
        }],
        unidade="",
    )

    trocas, total_de_trocas = consultas.trocas_de_rota_com_total(con)
    tabela = _tabela(
        ["dia", "hop", "de", "para"],
        [(t["dia"], t["hop"], t["de"], t["para"]) for t in trocas],
    )
    tabela += _rodape_tabela(len(trocas), total_de_trocas, "trocas de rota")

    return f"""<section>
<h2>A rota está instável</h2>
<p class="pergunta">O caminho até o destino está mudando ou quebrando?</p>
<h3>IPs distintos por hop, por dia</h3>
{grafico_ips}
<h3>Hops que não responderam</h3>
{grafico_desconhecidos}
<h3>Trocas de rota</h3>
{tabela}
</section>"""


def gerar(caminho_db):
    con = consultas.conectar(caminho_db)
    try:
        corpo = painel_culpado(con) + painel_baseline(con) + painel_rota(con)
        primeiro, ultimo = con.execute(
            "SELECT datetime(MIN(ts),'unixepoch','localtime'),"
            " datetime(MAX(ts),'unixepoch','localtime') FROM v_run"
        ).fetchone()
        total = con.execute("SELECT COUNT(*) FROM v_run").fetchone()[0]
    finally:
        con.close()

    periodo = (
        f"{total} execuções entre {escape(str(primeiro))} e {escape(str(ultimo))}."
        if total
        else "Sem dados no banco."
    )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mtr-log — análise de rede</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>Análise de rede</h1>
<p class="subtitulo">{periodo}</p>
{corpo}
<footer>Gerado por scripts/dashboard.py — sem dependências externas.</footer>
</main>
</body>
</html>"""

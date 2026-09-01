"""Primitivas de SVG. Recebe listas, devolve string. Não conhece o banco."""
from html import escape

# Paleta fixa. Centralizada para que nenhum painel invente cor própria.
CORES = {
    "lan": "#2563eb",
    "provedor": "#c2410c",
    "cgnat": "#d97706",
    "transito": "#7c3aed",
    "destino": "#0f766e",
    "p50": "#2563eb",
    "p95": "#dc2626",
    "neutro": "#64748b",
}

MARGEM = {"esq": 56, "dir": 18, "topo": 18, "base": 44}
VAZIO = '<p class="vazio">Sem dados no período.</p>'


def _projetar(valor, origem_min, origem_max, destino_min, destino_max):
    """Mapeia `valor` de um intervalo para outro, tolerando intervalo degenerado."""
    if origem_max == origem_min:
        return (destino_min + destino_max) / 2
    proporcao = (valor - origem_min) / (origem_max - origem_min)
    return destino_min + proporcao * (destino_max - destino_min)


def _eixo_y(v_min, v_max, topo, base, largura, unidade):
    """Cinco linhas de grade com rótulo."""
    partes = []
    for i in range(5):
        valor = v_min + (v_max - v_min) * i / 4
        y = _projetar(valor, v_min, v_max, base, topo)
        partes.append(
            f'<line x1="{MARGEM["esq"]}" y1="{y:.1f}"'
            f' x2="{largura - MARGEM["dir"]}" y2="{y:.1f}" class="grade"/>'
        )
        partes.append(
            f'<text x="{MARGEM["esq"] - 8}" y="{y + 4:.1f}" class="rotulo-y">'
            f'{valor:.1f}{escape(unidade)}</text>'
        )
    return "".join(partes)


def _legenda(series):
    itens = "".join(
        f'<span class="chave"><i style="background:{escape(s["cor"])}"></i>'
        f'{escape(s["nome"])}</span>'
        for s in series
    )
    return f'<div class="legenda">{itens}</div>'


def grafico_de_linhas(series, largura=900, altura=280, unidade=" ms"):
    """series: [{"nome", "cor", "pontos": [(rotulo_x, valor|None), ...]}, ...]

    Todas as séries devem compartilhar os mesmos rótulos de X, na mesma ordem.
    """
    series = [s for s in series if s.get("pontos")]
    if not series:
        return VAZIO

    valores = [v for s in series for _, v in s["pontos"] if v is not None]
    if not valores:
        return VAZIO

    rotulos = [rotulo for rotulo, _ in series[0]["pontos"]]
    total = len(rotulos)
    v_min, v_max = min(valores), max(valores)
    if v_max == v_min:
        v_max = v_min + 1

    esquerda, direita = MARGEM["esq"], largura - MARGEM["dir"]
    topo, base = MARGEM["topo"], altura - MARGEM["base"]

    partes = [f'<svg viewBox="0 0 {largura} {altura}" class="gr" role="img">']
    partes.append(_eixo_y(v_min, v_max, topo, base, largura, unidade))

    for serie in series:
        coordenadas = []
        for i, (_, valor) in enumerate(serie["pontos"]):
            if valor is None:
                continue
            x = _projetar(i, 0, max(total - 1, 1), esquerda, direita)
            y = _projetar(valor, v_min, v_max, base, topo)
            coordenadas.append(f"{x:.1f},{y:.1f}")
        if coordenadas:
            partes.append(
                f'<polyline points="{" ".join(coordenadas)}" fill="none"'
                f' stroke="{escape(serie["cor"])}" stroke-width="2"/>'
            )

    # Apenas primeiro, meio e último rótulo, para o eixo não virar um borrão.
    for i in sorted({0, total // 2, total - 1}):
        x = _projetar(i, 0, max(total - 1, 1), esquerda, direita)
        partes.append(
            f'<text x="{x:.1f}" y="{altura - 22}" class="rotulo-x">'
            f'{escape(str(rotulos[i]))}</text>'
        )

    partes.append("</svg>")
    partes.append(_legenda(series))
    return "".join(partes)


def grafico_de_barras(itens, largura=900, altura=260, unidade=" ms"):
    """itens: [{"rotulo": str, "valor": float, "cor": str}, ...]"""
    itens = [i for i in itens if i.get("valor") is not None]
    if not itens:
        return VAZIO

    v_max = max(item["valor"] for item in itens)
    if v_max <= 0:
        v_max = 1

    esquerda, direita = MARGEM["esq"], largura - MARGEM["dir"]
    topo, base = MARGEM["topo"], altura - MARGEM["base"]
    faixa = (direita - esquerda) / len(itens)
    largura_barra = faixa * 0.55

    partes = [f'<svg viewBox="0 0 {largura} {altura}" class="gr" role="img">']
    partes.append(_eixo_y(0, v_max, topo, base, largura, unidade))

    for i, item in enumerate(itens):
        centro = esquerda + faixa * (i + 0.5)
        y = _projetar(item["valor"], 0, v_max, base, topo)
        partes.append(
            f'<rect x="{centro - largura_barra / 2:.1f}" y="{y:.1f}"'
            f' width="{largura_barra:.1f}" height="{max(base - y, 0):.1f}"'
            f' fill="{escape(item["cor"])}" rx="3"/>'
        )
        partes.append(
            f'<text x="{centro:.1f}" y="{y - 6:.1f}" class="valor-barra">'
            f'{item["valor"]:.2f}</text>'
        )
        partes.append(
            f'<text x="{centro:.1f}" y="{altura - 22}" class="rotulo-x">'
            f'{escape(item["rotulo"])}</text>'
        )

    partes.append("</svg>")
    return "".join(partes)

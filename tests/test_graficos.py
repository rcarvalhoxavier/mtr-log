"""Testes das primitivas de SVG."""
import pathlib
import sys
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from mtrdash import graficos  # noqa: E402


class TestGraficoDeLinhas(unittest.TestCase):
    def serie(self, pontos, nome="p50"):
        return [{"nome": nome, "cor": "#2563eb", "pontos": pontos}]

    def test_sem_series_devolve_marcacao_de_vazio(self):
        self.assertEqual(graficos.grafico_de_linhas([]), graficos.VAZIO)

    def test_serie_sem_pontos_devolve_vazio(self):
        self.assertEqual(graficos.grafico_de_linhas(self.serie([])), graficos.VAZIO)

    def test_serie_so_com_nulos_devolve_vazio(self):
        svg = graficos.grafico_de_linhas(self.serie([("a", None), ("b", None)]))
        self.assertEqual(svg, graficos.VAZIO)

    def test_gera_polyline_com_um_par_por_ponto(self):
        svg = graficos.grafico_de_linhas(
            self.serie([("2026-08-29", 8.0), ("2026-08-30", 9.0), ("2026-08-31", 7.0)])
        )
        self.assertIn("<polyline", svg)
        pontos = svg.split('points="')[1].split('"')[0]
        self.assertEqual(len(pontos.split()), 3)

    def test_valores_iguais_nao_dividem_por_zero(self):
        svg = graficos.grafico_de_linhas(
            self.serie([("a", 5.0), ("b", 5.0), ("c", 5.0)])
        )
        self.assertIn("<polyline", svg)
        self.assertNotIn("nan", svg.lower())

    def test_ponto_nulo_e_omitido_da_polyline(self):
        svg = graficos.grafico_de_linhas(
            self.serie([("a", 1.0), ("b", None), ("c", 3.0)])
        )
        pontos = svg.split('points="')[1].split('"')[0]
        self.assertEqual(len(pontos.split()), 2)

    def test_duas_series_geram_duas_polylines(self):
        series = [
            {"nome": "p50", "cor": "#2563eb", "pontos": [("a", 1.0), ("b", 2.0)]},
            {"nome": "p95", "cor": "#dc2626", "pontos": [("a", 3.0), ("b", 4.0)]},
        ]
        self.assertEqual(graficos.grafico_de_linhas(series).count("<polyline"), 2)

    def test_rotulo_hostil_e_escapado(self):
        svg = graficos.grafico_de_linhas(
            self.serie([("<script>", 1.0), ("b", 2.0)], nome="<b>x</b>")
        )
        self.assertNotIn("<script>", svg)
        self.assertNotIn("<b>x</b>", svg)
        self.assertIn("&lt;script&gt;", svg)

    def test_cor_hostil_e_escapada_na_polyline(self):
        svg = graficos.grafico_de_linhas(
            [{"nome": "p50", "cor": '"><script>', "pontos": [("a", 1.0), ("b", 2.0)]}]
        )
        self.assertNotIn('"><script>', svg)
        self.assertIn("&quot;&gt;&lt;script&gt;", svg)

    def test_cor_hostil_e_escapada_na_legenda(self):
        svg = graficos.grafico_de_linhas(
            [{"nome": "p50", "cor": "<img src=x>", "pontos": [("a", 1.0), ("b", 2.0)]}]
        )
        self.assertNotIn("<img src=x>", svg)
        self.assertIn("&lt;img src=x&gt;", svg)


class TestGraficoDeBarras(unittest.TestCase):
    ITENS = [
        {"rotulo": "lan", "valor": 0.8, "cor": "#2563eb"},
        {"rotulo": "cgnat", "valor": 3.4, "cor": "#d97706"},
        {"rotulo": "transito", "valor": 8.1, "cor": "#7c3aed"},
    ]

    def test_sem_itens_devolve_vazio(self):
        self.assertEqual(graficos.grafico_de_barras([]), graficos.VAZIO)

    def test_uma_barra_por_item(self):
        self.assertEqual(graficos.grafico_de_barras(self.ITENS).count("<rect"), 3)

    def test_itens_com_valor_nulo_sao_ignorados(self):
        itens = self.ITENS + [{"rotulo": "x", "valor": None, "cor": "#000"}]
        self.assertEqual(graficos.grafico_de_barras(itens).count("<rect"), 3)

    def test_todos_zerados_nao_dividem_por_zero(self):
        itens = [{"rotulo": "a", "valor": 0.0, "cor": "#000"}]
        svg = graficos.grafico_de_barras(itens)
        self.assertIn("<rect", svg)
        self.assertNotIn("nan", svg.lower())

    def test_rotulo_hostil_e_escapado(self):
        itens = [{"rotulo": "<img src=x>", "valor": 1.0, "cor": "#000"}]
        self.assertNotIn("<img", graficos.grafico_de_barras(itens))

    def test_cor_hostil_e_escapada_no_rect(self):
        itens = [{"rotulo": "a", "valor": 1.0, "cor": '"><script>'}]
        svg = graficos.grafico_de_barras(itens)
        self.assertNotIn('"><script>', svg)
        self.assertIn("&quot;&gt;&lt;script&gt;", svg)

    def test_cor_hostil_e_escapada_na_legenda_barras(self):
        itens = [{"rotulo": "a", "valor": 1.0, "cor": "<img src=x>"}]
        svg = graficos.grafico_de_barras(itens)
        self.assertNotIn("<img src=x>", svg)


class TestPaleta(unittest.TestCase):
    def test_tem_uma_cor_por_segmento(self):
        for chave in ("lan", "cgnat", "transito", "destino", "p50", "p95", "neutro"):
            self.assertIn(chave, graficos.CORES)


if __name__ == "__main__":
    unittest.main()

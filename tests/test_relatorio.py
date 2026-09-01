"""Testes de geração do HTML, ponta a ponta."""
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from mtrdash import consultas, relatorio  # noqa: E402

SCHEMA = RAIZ / "scripts" / "schema.sql"
DASHBOARD = RAIZ / "scripts" / "dashboard.py"
BASE_TS = 1785196800
UM_DIA = 86400


def banco_com(linhas):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    con = sqlite3.connect(tmp.name)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executemany(
        "INSERT OR IGNORE INTO mtr_data (ts, host, hop, ip, loss, avg, best, drops, snt)"
        " VALUES (?, '8.8.8.8', ?, ?, ?, ?, ?, ?, 10)",
        linhas,
    )
    con.commit()
    con.close()
    return tmp.name


def banco_realista():
    linhas = []
    for dia in range(10):
        for n in range(3):
            ts = BASE_TS + dia * UM_DIA + n * 3600
            linhas += [
                (ts, 1, "_gateway", 0.0, 1.0, 0.8, 0),
                (ts, 2, "100.70.0.1", 0.0, 4.0, 3.4, 0),
                (ts, 3, "142.251.200.106" if dia < 5 else "209.85.173.108",
                 0.0, 8.0, 7.0, 0),
                (ts, 4, None, 100.0, 0.0, 0.0, 10),
                (ts, 5, "dns.google", 10.0 if (dia == 7 and n == 0) else 0.0,
                 9.0 + dia * 0.4, 8.0, 1 if (dia == 7 and n == 0) else 0),
            ]
    return banco_com(linhas)


class TestGeracao(unittest.TestCase):
    def setUp(self):
        self.caminho = banco_realista()
        self.html = relatorio.gerar(self.caminho)

    def tearDown(self):
        pathlib.Path(self.caminho).unlink()

    def test_tem_os_tres_paineis(self):
        for titulo in ("De quem é a culpa", "Está pior que o normal",
                       "A rota está instável"):
            self.assertIn(titulo, self.html)

    def test_e_um_documento_completo(self):
        self.assertTrue(self.html.startswith("<!doctype html>"))
        self.assertIn('<html lang="pt-BR">', self.html)
        self.assertIn("</html>", self.html)

    def test_desenha_graficos(self):
        self.assertGreaterEqual(self.html.count("<svg"), 4)

    def test_nao_referencia_nada_externo(self):
        """Requisito de autocontenção: nada de CDN, webfont ou script externo."""
        for proibido in ("http://", "https://", "<script", "@import"):
            self.assertNotIn(proibido, self.html)

    def test_registra_a_troca_de_rota(self):
        self.assertIn("142.251.200.106", self.html)
        self.assertIn("209.85.173.108", self.html)

    def test_separa_perda_real_de_artefato(self):
        """O hop 4 perde 100% nas 30 execuções, mas o destino só perde em uma.
        Logo: 29 artefatos e 1 perda real. Conferido na nota do painel, não por
        substring solta, que passaria por acidente."""
        self.assertIn("<strong>29</strong> execuções", self.html)
        self.assertIn("<strong>1</strong> execuções de perda real", self.html)
        self.assertIn("não chegou ao destino", self.html)

    def test_nao_vaza_a_interrogacao_do_mtr(self):
        self.assertNotIn("???", self.html)


class TestAlinhamentoDeEixo(unittest.TestCase):
    """O painel_rota monta um eixo de dias comum e preenche com None onde um
    hop não tem medição — cada hop pode ter seu próprio conjunto de dias.
    grafico_de_linhas tira os rótulos de X de series[0] e posiciona cada
    ponto pelo índice: se um painel passar séries com tamanhos diferentes
    (por exemplo, o próprio dicionário de cada hop, sem preencher os dias
    ausentes), pontos de dias diferentes acabam na mesma posição x, sem
    nenhum sinal de erro. Este teste comprova que a posição x de um ponto
    representa o dia certo, não apenas o índice dentro dos dados daquele hop."""

    def test_hop_com_menos_dias_cai_na_posicao_x_correta(self):
        # hop 1 mede nos três dias; hop 2 só mede no último.
        linhas = [
            (BASE_TS, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (BASE_TS + UM_DIA, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (BASE_TS + 2 * UM_DIA, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (BASE_TS + 2 * UM_DIA, 2, "1.2.3.4", 0.0, 4.0, 3.4, 0),
        ]
        caminho = banco_com(linhas)
        try:
            con = consultas.conectar(caminho)
            try:
                html = relatorio.painel_rota(con)
            finally:
                con.close()

            polylines = re.findall(r'<polyline points="([^"]+)"', html)
            # A primeira polyline (hop 1, ordenado primeiro) tem os três dias;
            # a segunda (hop 2) tem só o último.
            self.assertGreaterEqual(len(polylines), 2)
            pontos_hop1 = polylines[0].split()
            pontos_hop2 = polylines[1].split()
            self.assertEqual(len(pontos_hop1), 3)
            self.assertEqual(len(pontos_hop2), 1)

            x_ultimo_hop1 = pontos_hop1[-1].split(",")[0]
            x_unico_hop2 = pontos_hop2[0].split(",")[0]
            self.assertEqual(
                x_unico_hop2, x_ultimo_hop1,
                "o único ponto do hop 2 (medido no último dia) deveria cair "
                "na mesma posição x do último ponto do hop 1, não na posição "
                "inicial do eixo",
            )
        finally:
            pathlib.Path(caminho).unlink()


class TestCartaoRecente(unittest.TestCase):
    """painel_baseline lê `recente` e `baseline` do dicionário devolvido por
    consultas.comparacao_baseline e usa os dois para montar cada cartão. Uma
    troca acidental dessas duas chaves não quebra nada visível: os cartões
    continuam com números plausíveis, só que o valor "atual" exibido passa a
    ser o histórico e vice-versa, e a classe pior/melhor se inverte junto.
    Nenhum teste anterior comparava o valor exibido no cartão contra o valor
    esperado da janela recente — só a presença de texto solto como "Está pior
    que o normal" — por isso essa troca passaria em silêncio."""

    ULTIMO_TS = BASE_TS + 200 * UM_DIA
    # Bem além da janela recente (consultas.DIAS_JANELA_RECENTE dias), para não
    # haver ambiguidade sobre quais execuções caem em cada lado do corte.
    MARGEM_HISTORICO = consultas.DIAS_JANELA_RECENTE + 5

    def _banco_com_janelas(self, valor_recente, valor_historico):
        """3 execuções dentro da janela recente com latência constante
        `valor_recente`, e 20 execuções bem mais antigas com latência
        constante `valor_historico`. Um único hop (destino direto), sem
        perda, para que p50 de cada janela seja exatamente o valor
        constante correspondente — sem depender do método de percentil."""
        linhas = []
        for k in range(3):
            ts = self.ULTIMO_TS - k * UM_DIA
            linhas.append((ts, 1, "8.8.4.4", 0.0, valor_recente, valor_recente, 0))
        for k in range(20):
            ts = self.ULTIMO_TS - (self.MARGEM_HISTORICO + k) * UM_DIA
            linhas.append((ts, 1, "8.8.4.4", 0.0, valor_historico, valor_historico, 0))
        return banco_com(linhas)

    def test_janela_recente_pior_mostra_valor_recente_e_classe_pior(self):
        caminho = self._banco_com_janelas(valor_recente=50.0, valor_historico=5.0)
        try:
            con = consultas.conectar(caminho)
            try:
                html = relatorio.painel_baseline(con)
            finally:
                con.close()
            self.assertIn(
                '<div class="cartao"><div class="titulo">Latência mediana</div>'
                '<div class="valor">50.00 ms</div>'
                '<div class="delta pior">+45.00 ms vs baseline 5.00 ms</div></div>',
                html,
            )
        finally:
            pathlib.Path(caminho).unlink()

    def test_janela_recente_melhor_mostra_valor_recente_e_classe_melhor(self):
        caminho = self._banco_com_janelas(valor_recente=5.0, valor_historico=50.0)
        try:
            con = consultas.conectar(caminho)
            try:
                html = relatorio.painel_baseline(con)
            finally:
                con.close()
            self.assertIn(
                '<div class="cartao"><div class="titulo">Latência mediana</div>'
                '<div class="valor">5.00 ms</div>'
                '<div class="delta melhor">-45.00 ms vs baseline 50.00 ms</div></div>',
                html,
            )
        finally:
            pathlib.Path(caminho).unlink()


class TestRobustez(unittest.TestCase):
    def test_banco_vazio_nao_quebra(self):
        caminho = banco_com([])
        try:
            html = relatorio.gerar(caminho)
            self.assertIn("</html>", html)
            self.assertIn("Sem dados", html)
        finally:
            pathlib.Path(caminho).unlink()

    def test_conteudo_hostil_do_banco_e_escapado(self):
        """Um hostname reverso é dado de terceiro; nunca vai cru para o HTML."""
        linhas = [
            (BASE_TS, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (BASE_TS, 2, "<script>alert(1)</script>", 0.0, 4.0, 3.4, 0),
            (BASE_TS + UM_DIA, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (BASE_TS + UM_DIA, 2, "outro.exemplo", 0.0, 4.0, 3.4, 0),
        ]
        caminho = banco_com(linhas)
        try:
            html = relatorio.gerar(caminho)
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertIn("&lt;script&gt;", html)
        finally:
            pathlib.Path(caminho).unlink()


class TestPontoDeEntrada(unittest.TestCase):
    def test_escreve_o_arquivo(self):
        caminho = banco_realista()
        saida = pathlib.Path(tempfile.gettempdir()) / "dashboard-teste.html"
        try:
            resultado = subprocess.run(
                [sys.executable, str(DASHBOARD), "--banco", caminho,
                 "--saida", str(saida)],
                capture_output=True, text=True,
            )
            self.assertEqual(resultado.returncode, 0, resultado.stderr)
            self.assertTrue(saida.exists())
            self.assertIn("De quem é a culpa", saida.read_text(encoding="utf-8"))
        finally:
            pathlib.Path(caminho).unlink()
            saida.unlink(missing_ok=True)

    def test_banco_inexistente_falha_com_mensagem(self):
        resultado = subprocess.run(
            [sys.executable, str(DASHBOARD), "--banco", "/nao/existe.db"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("não encontrado", resultado.stderr)


if __name__ == "__main__":
    unittest.main()

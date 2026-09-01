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

    def test_tem_as_tres_secoes(self):
        for titulo in ("Últimas execuções", "De quem é a culpa",
                       "Está pior que o normal"):
            self.assertIn(titulo, self.html)

    def test_nao_tem_mais_o_painel_de_rota(self):
        """Removido: dois dos três componentes mediam o balanceador de carga do
        destino, não a rede do usuário — 72% dos pares hop-dia tinham exatamente um
        IP, e 596 das 887 trocas estavam em hops do próprio Google."""
        self.assertNotIn("A rota está instável", self.html)

    def test_e_um_documento_completo(self):
        self.assertTrue(self.html.startswith("<!doctype html>"))
        self.assertIn('<html lang="pt-BR">', self.html)
        self.assertIn("</html>", self.html)

    def test_desenha_os_tres_graficos(self):
        """Latência diária e barras por segmento em "De quem é a culpa", mais a série
        dos últimos 30 dias em "Está pior que o normal"."""
        self.assertEqual(self.html.count("<svg"), 3)

    def test_nao_referencia_nada_externo(self):
        """Requisito de autocontenção: nada de CDN, webfont ou script externo."""
        for proibido in ("http://", "https://", "<script", "@import"):
            self.assertNotIn(proibido, self.html)

    def test_separa_perda_real_de_artefato(self):
        """O hop 4 perde 100% nas 30 execuções, mas o destino só perde em uma.
        Logo: 29 artefatos e 1 perda real. Conferido na nota do painel, não por
        substring solta, que passaria por acidente."""
        self.assertIn("<strong>29</strong> execuções", self.html)
        self.assertIn(
            "<strong>1</strong> de <strong>1</strong> execuções de perda real",
            self.html,
        )
        self.assertIn("não chegou ao destino", self.html)
        # Toda execução desta fixture termina em dns.google, então nenhuma é
        # truncada — o caminho feliz que escondia o bug das traces incompletas.
        self.assertIn("<strong>0</strong> execuções não chegaram ao alvo", self.html)

    def test_nao_vaza_a_interrogacao_do_mtr(self):
        self.assertNotIn("???", self.html)


class TestNotaDoPainel1(unittest.TestCase):
    """A nota é o único lugar do dashboard onde os números descartados são
    explicados. Ela precisa contar as traces truncadas separadamente e dizer a
    verdade sobre o tamanho da tabela ao lado."""

    def _banco_com_incompletas(self):
        linhas = []
        # 3 execuções completas e limpas.
        for n in range(3):
            ts = BASE_TS + n * 3600
            linhas += [
                (ts, 1, "_gateway", 0.0, 1.0, 0.8, 0),
                (ts, 2, "dns.google", 0.0, 9.0, 8.0, 0),
            ]
        # 1 execução completa com perda que chegou ao destino: perda real.
        ts = BASE_TS + 10 * 3600
        linhas += [
            (ts, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (ts, 2, "dns.google", 20.0, 9.0, 8.0, 2),
        ]
        # 5 execuções truncadas no gateway, com perda: nem real, nem artefato.
        for n in range(5):
            ts = BASE_TS + UM_DIA + n * 3600
            linhas.append((ts, 1, "_gateway", 100.0, 1.24, 1.10, 10))
        return banco_com(linhas)

    def test_reporta_incompletas_separadamente_da_perda_real(self):
        caminho = self._banco_com_incompletas()
        try:
            con = consultas.conectar(caminho)
            try:
                html = relatorio.painel_culpado(con)
            finally:
                con.close()
            self.assertIn("<strong>5</strong> execuções não chegaram ao alvo", html)
            self.assertIn("caminho parcial", html)
            # A perda real continua sendo só a execução que de fato chegou.
            self.assertIn(
                "<strong>1</strong> de <strong>1</strong> execuções de perda real",
                html,
            )
        finally:
            pathlib.Path(caminho).unlink()

    def test_tabela_de_perda_diz_quantas_mostra_de_quantas_existem(self):
        """A nota afirmava que a tabela listava as 1205 execuções de perda real.
        A tabela tem 40 linhas: `eventos_de_perda` trunca em `limite=40`."""
        linhas = []
        for n in range(45):
            ts = BASE_TS + n * 3600
            linhas += [
                (ts, 1, "_gateway", 0.0, 1.0, 0.8, 0),
                (ts, 2, "dns.google", 5.0, 9.0, 8.0, 1),
            ]
        caminho = banco_com(linhas)
        try:
            con = consultas.conectar(caminho)
            try:
                html = relatorio.painel_culpado(con)
            finally:
                con.close()
            self.assertIn(
                "<strong>40</strong> de <strong>45</strong> execuções de perda real",
                html,
            )
            # Escopado à tabela de perda: contar <tr> no painel inteiro fazia este
            # teste quebrar quando qualquer outra tabela era acrescentada ao painel.
            tabela = html[html.index("Eventos de perda real"):]
            corpo = re.search(r"<tbody>(.*?)</tbody>", tabela, re.S).group(1)
            self.assertEqual(len(re.findall(r"<tr>", corpo)), 40)
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
        constante `valor_historico`. Sem perda, para que p50 de cada janela
        seja exatamente o valor constante correspondente — sem depender do
        método de percentil.

        O gateway no hop 1 não é decoração: o hop 1 é `lan` por definição
        (spec §3.2), então uma execução de um hop só nunca chega ao destino e
        é descartada das séries de latência. A trace precisa terminar em
        `transito` para valer como medição do destino."""
        linhas = []
        for k in range(3):
            ts = self.ULTIMO_TS - k * UM_DIA
            linhas.append((ts, 1, "_gateway", 0.0, 1.0, 0.8, 0))
            linhas.append((ts, 2, "8.8.4.4", 0.0, valor_recente, valor_recente, 0))
        for k in range(20):
            ts = self.ULTIMO_TS - (self.MARGEM_HISTORICO + k) * UM_DIA
            linhas.append((ts, 1, "_gateway", 0.0, 1.0, 0.8, 0))
            linhas.append((ts, 2, "8.8.4.4", 0.0, valor_historico, valor_historico, 0))
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


def matriz_de_hops(html):
    """Linhas da matriz hop x execução, como listas de texto de célula."""
    bloco = html[html.index('class="matriz"'):]
    corpo = re.search(r"<tbody>(.*?)</tbody>", bloco, re.S).group(1)
    return [
        [re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<td[^>]*>.*?</td>", tr, re.S)]
        for tr in re.findall(r"<tr>(.*?)</tr>", corpo, re.S)
    ]


def legenda_de_situacao(html):
    """Pares (situação, significado) da tabela de legenda, e só dela.

    Escopar importa: as palavras da legenda também aparecem na coluna `situação` da
    tira de status, então procurá-las no HTML inteiro passa mesmo com a legenda
    removida.
    """
    bloco = html[html.index("O que cada situação quer dizer"):html.index('class="matriz"')]
    corpo = re.search(r"<tbody>(.*?)</tbody>", bloco, re.S).group(1)
    return [
        tuple(re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<td[^>]*>.*?</td>", tr, re.S))
        for tr in re.findall(r"<tr>(.*?)</tr>", corpo, re.S)
    ]


def legenda_de_segmento(html):
    """Pares (segmento, descrição) da legenda do gráfico de barras, e só dela.

    Escopar de novo: `lan`, `cgnat`, `transito` e `destino` também aparecem como
    rótulos do eixo X do SVG no mesmo painel, então procurar no HTML inteiro passa
    mesmo com a legenda removida.
    """
    bloco = html[html.index("O que é cada segmento"):html.index("Eventos de perda real")]
    corpo = re.search(r"<tbody>(.*?)</tbody>", bloco, re.S).group(1)
    return [
        tuple(re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<td[^>]*>.*?</td>", tr, re.S))
        for tr in re.findall(r"<tr>(.*?)</tr>", corpo, re.S)
    ]


class TestPainelAgora(unittest.TestCase):
    """A seção "Agora": as últimas execuções, para diagnosticar uma interrupção."""

    def _banco(self):
        linhas = [
            # Mais antiga: chegou ao destino, três hops.
            (BASE_TS, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (BASE_TS, 2, "100.70.0.1", 0.0, 4.0, 3.4, 0),
            (BASE_TS, 3, "dns.google", 0.0, 9.0, 8.0, 0),
            # Mais recente: morreu no gateway, como na queda real de nov/2025.
            (BASE_TS + 300, 1, "_gateway", 90.0, 0.93, 0.9, 9),
        ]
        return banco_com(linhas)

    def _painel(self):
        caminho = self._banco()
        try:
            con = consultas.conectar(caminho)
            try:
                return relatorio.painel_agora(con)
            finally:
                con.close()
        finally:
            pathlib.Path(caminho).unlink()

    def test_uma_linha_por_execucao_na_tira_de_status(self):
        html = self._painel()
        tira = html[html.index("Últimas execuções"):html.index('class="matriz"')]
        self.assertEqual(len(re.findall(r"<tr>", re.search(r"<tbody>(.*?)</tbody>", tira, re.S).group(1))), 2)

    def test_matriz_mostra_a_parede_onde_a_trace_parou(self):
        """O eixo de hops é comum às execuções. Uma trace que parou no hop 1 deixa
        as células dos hops 2 e 3 vazias, e é essa parede que mostra onde quebrou."""
        linhas = matriz_de_hops(self._painel())
        self.assertEqual([l[0] for l in linhas], ["1", "2", "3"])
        # Coluna 1 é a execução mais recente (truncada); coluna 2 é a antiga.
        self.assertNotEqual(linhas[0][1], "")
        self.assertEqual(linhas[1][1], "")
        self.assertEqual(linhas[2][1], "")
        self.assertNotEqual(linhas[1][2], "")
        self.assertNotEqual(linhas[2][2], "")

    def test_celula_traz_ip_latencia_e_perda_quando_ha_perda(self):
        linhas = matriz_de_hops(self._painel())
        recente_hop1 = linhas[0][1]
        self.assertIn("_gateway", recente_hop1)
        self.assertIn("0.9 ms", recente_hop1)
        self.assertIn("90%", recente_hop1)

    def test_celula_omite_perda_quando_nao_ha(self):
        linhas = matriz_de_hops(self._painel())
        antiga_hop3 = linhas[2][2]
        self.assertIn("dns.google", antiga_hop3)
        self.assertNotIn("%", antiga_hop3)

    def test_legenda_define_as_quatro_situacoes(self):
        """A coluna `situação` mostra a palavra crua. Sem a legenda ao lado, quem abre
        o dashboard no meio de uma interrupção lê `artefato` sem ter contexto."""
        pares = legenda_de_situacao(self._painel())
        self.assertEqual(
            [valor for valor, _ in pares],
            ["sem_perda", "real", "artefato", "incompleta"],
        )

    def test_legenda_explica_artefato_como_limitacao_de_icmp(self):
        significados = dict(legenda_de_situacao(self._painel()))
        self.assertIn("ICMP", significados["artefato"])

    def test_legenda_vem_entre_a_tira_de_status_e_a_matriz(self):
        html = self._painel()
        self.assertLess(html.index("chegou ao alvo"), html.index("significado"))
        self.assertLess(html.index("significado"), html.index('class="matriz"'))

    def test_hop_sem_resposta_nao_exibe_latencia(self):
        """O mtr grava avg 0.0 para um hop que não respondeu. Isso é ausência de
        medição, não latência zero — exibir como número diria que aquele salto é
        instantâneo, que é o oposto da verdade."""
        caminho = banco_com([
            (BASE_TS, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (BASE_TS, 2, None, 100.0, 0.0, 0.0, 10),
            (BASE_TS, 3, "dns.google", 0.0, 9.0, 8.0, 0),
        ])
        try:
            con = consultas.conectar(caminho)
            try:
                linhas = matriz_de_hops(relatorio.painel_agora(con))
            finally:
                con.close()
        finally:
            pathlib.Path(caminho).unlink()
        celula = linhas[1][1]
        self.assertIn("sem resposta", celula)
        self.assertNotIn("ms", celula)
        self.assertNotIn("0.0", celula)

    def test_linha_de_frescor_data_a_geracao_nao_um_agora_vivo(self):
        """O arquivo é estático. Dizer "há 4 minutos" sem ancorar na geração vira
        mentira no dia seguinte."""
        html = self._painel()
        self.assertIn("Gerado em", html)
        self.assertIn("antes", html)

    def test_secao_agora_vem_antes_dos_paineis_historicos(self):
        caminho = self._banco()
        try:
            html = relatorio.gerar(caminho)
        finally:
            pathlib.Path(caminho).unlink()
        self.assertLess(html.index("Últimas execuções"), html.index("De quem é a culpa"))

    def test_banco_vazio_nao_quebra(self):
        caminho = banco_com([])
        try:
            con = consultas.conectar(caminho)
            try:
                self.assertIn("Sem dados", relatorio.painel_agora(con))
            finally:
                con.close()
        finally:
            pathlib.Path(caminho).unlink()


class TestLegendaDeSegmento(unittest.TestCase):
    """A legenda do gráfico "Latência mínima por segmento do caminho"."""

    def _painel(self):
        caminho = banco_com([
            (BASE_TS, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (BASE_TS, 2, "100.70.0.1", 0.0, 4.0, 3.4, 0),
            (BASE_TS, 3, "dns.google", 30.0, 9.0, 8.0, 3),
        ])
        try:
            con = consultas.conectar(caminho)
            try:
                return relatorio.painel_culpado(con)
            finally:
                con.close()
        finally:
            pathlib.Path(caminho).unlink()

    def test_define_as_quatro_barras_na_ordem_do_grafico(self):
        pares = legenda_de_segmento(self._painel())
        self.assertEqual(
            [rotulo for rotulo, _ in pares],
            ["lan", "cgnat", "transito", "destino"],
        )

    def test_revela_que_destino_esta_contado_dentro_de_transito(self):
        """As duas barras não são disjuntas: o hop de destino é sempre classificado
        como transito. Sem dizer isso, quem compara as barras conclui errado."""
        descricoes = dict(legenda_de_segmento(self._painel()))
        self.assertIn("transito", descricoes["destino"])

    def test_explica_a_faixa_de_cgnat(self):
        descricoes = dict(legenda_de_segmento(self._painel()))
        self.assertIn("100.64.0.0/10", descricoes["cgnat"])

    def test_legenda_omite_segmento_sem_barra(self):
        """Topologia sem CGNAT visível não desenha essa barra. Explicar um segmento
        ausente manda o leitor procurar no gráfico algo que não está lá."""
        caminho = banco_com([
            (BASE_TS, 1, "192.168.5.1", 0.0, 1.0, 0.5, 0),
            (BASE_TS, 2, "192.168.0.1", 0.0, 3.0, 1.4, 0),
            (BASE_TS, 3, "dns.google", 0.0, 9.0, 8.0, 0),
        ])
        try:
            con = consultas.conectar(caminho)
            try:
                html = relatorio.painel_culpado(con)
            finally:
                con.close()
        finally:
            pathlib.Path(caminho).unlink()
        rotulos = [r for r, _ in legenda_de_segmento(html)]
        self.assertIn("provedor", rotulos)
        self.assertNotIn("cgnat", rotulos)

    def test_vem_depois_do_grafico_e_antes_da_tabela_de_perda(self):
        html = self._painel()
        self.assertLess(html.index("Latência mínima por segmento"),
                        html.index("O que é cada segmento"))
        self.assertLess(html.index("O que é cada segmento"),
                        html.index("Eventos de perda real"))

    def test_nota_justifica_o_uso_da_latencia_minima(self):
        html = self._painel()
        inicio = html.index("O que é cada segmento")
        trecho = html[inicio:html.index("Eventos de perda real")]
        self.assertIn("ICMP", trecho)
        self.assertIn("mínima", trecho)


class TestAlinhamentoDeTabela(unittest.TestCase):
    """Cabeçalho e células de uma coluna numérica têm que concordar no alinhamento.

    A versão anterior decidia o alinhamento por célula, olhando o tipo Python, então
    uma coluna de inteiros saía com o `th` à esquerda e os `td` à direita, e o número
    aparecia solto, longe do próprio cabeçalho.
    """

    def test_coluna_numerica_alinha_cabecalho_junto_com_as_celulas(self):
        html = relatorio._tabela(
            ["quando", "perda", "pacotes"],
            [("2026-08-31", "10.00%", 3)],
            colunas_numericas=(1, 2),
        )
        self.assertIn('<th class="num">perda</th>', html)
        self.assertIn('<th class="num">pacotes</th>', html)
        self.assertIn('<td class="num">10.00%</td>', html)
        self.assertIn('<td class="num">3</td>', html)

    def test_coluna_de_texto_nao_recebe_alinhamento(self):
        html = relatorio._tabela(["quando"], [("2026-08-31",)])
        self.assertIn("<th>quando</th>", html)
        self.assertIn("<td>2026-08-31</td>", html)
        self.assertNotIn("num", html)

    def test_alinhamento_nao_depende_do_tipo_da_celula(self):
        """`_numero` devolve string, e valor ausente vira travessão: os dois
        continuam na coluna numérica."""
        html = relatorio._tabela(
            ["perda"],
            [(relatorio._numero(10.0, 2, "%"),), (relatorio._numero(None),)],
            colunas_numericas=(0,),
        )
        self.assertIn('<td class="num">10.00%</td>', html)
        self.assertIn('<td class="num">—</td>', html)

    def test_painel_declara_as_colunas_numericas_da_tabela_de_perda(self):
        """Guarda o ponto de chamada: remover `colunas_numericas` de painel_culpado
        não seria pego pelos testes de unidade acima."""
        caminho = banco_com([
            (BASE_TS, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (BASE_TS, 2, "dns.google", 30.0, 9.0, 8.0, 3),
        ])
        try:
            con = consultas.conectar(caminho)
            try:
                html = relatorio.painel_culpado(con)
            finally:
                con.close()
            self.assertIn('<th class="num">pacotes perdidos</th>', html)
            self.assertIn('<th class="num">hops</th>', html)
            self.assertIn('<th class="num">perda no destino</th>', html)
            self.assertIn("<th>quando</th>", html)
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

    def test_subtitulo_ignora_timestamp_implausivel(self):
        """Uma escrita de CSV interrompida desloca as colunas e o Start_Time recebe um
        fragmento de latência, virando epoch ~0 na migração. Sem piso, a primeira
        frase do dashboard anuncia 1969."""
        caminho = banco_com([
            (13, 1, "lixo", 0.0, None, None, 0),
            (BASE_TS, 1, "_gateway", 0.0, 1.0, 0.8, 0),
            (BASE_TS, 2, "dns.google", 0.0, 9.0, 8.0, 0),
        ])
        try:
            html = relatorio.gerar(caminho)
        finally:
            pathlib.Path(caminho).unlink()
        self.assertNotIn("1969", html)
        self.assertIn("2026", html)

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

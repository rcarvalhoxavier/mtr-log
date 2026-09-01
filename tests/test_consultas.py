"""Testes das consultas e da estatística."""
import pathlib
import sqlite3
import sys
import tempfile
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

from mtrdash import consultas  # noqa: E402

SCHEMA = RAIZ / "scripts" / "schema.sql"
UM_DIA = 86400
BASE_TS = 1785196800  # 2026-08-26 00:00:00 UTC


def construir_banco(linhas):
    """linhas: [(ts, hop, ip, loss, avg, best), ...]. Devolve o caminho do arquivo."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    con = sqlite3.connect(tmp.name)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    con.executemany(
        "INSERT OR IGNORE INTO mtr_data (ts, host, hop, ip, loss, avg, best, drops, snt)"
        " VALUES (?, '8.8.8.8', ?, ?, ?, ?, ?, 0, 10)",
        linhas,
    )
    con.commit()
    con.close()
    return tmp.name


def execucao(ts, hops):
    """hops: [(hop, ip, loss, avg, best), ...] -> linhas para construir_banco."""
    return [(ts, h, ip, loss, avg, best) for h, ip, loss, avg, best in hops]


class TestPercentil(unittest.TestCase):
    def test_valores_conhecidos(self):
        dados = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        self.assertEqual(consultas.percentil(dados, 50), 5)
        self.assertEqual(consultas.percentil(dados, 95), 10)
        self.assertEqual(consultas.percentil(dados, 100), 10)

    def test_nao_depende_da_ordem_de_entrada(self):
        self.assertEqual(consultas.percentil([9, 1, 5, 3, 7], 50), 5)

    def test_lista_vazia(self):
        self.assertIsNone(consultas.percentil([], 50))

    def test_um_elemento(self):
        self.assertEqual(consultas.percentil([42], 50), 42)
        self.assertEqual(consultas.percentil([42], 95), 42)


class TestConsultas(unittest.TestCase):
    def setUp(self):
        linhas = []
        # Dois dias, duas execuções por dia.
        for dia in (0, 1):
            for n in (0, 1):
                ts = BASE_TS + dia * UM_DIA + n * 3600
                linhas += execucao(ts, [
                    (1, "_gateway", 0.0, 1.0, 0.8),
                    (2, "100.70.0.1", 0.0, 4.0, 3.4),
                    (3, "dns.google", 0.0, 10.0 + dia, 8.0 + dia),
                ])
        self.caminho = construir_banco(linhas)
        self.con = consultas.conectar(self.caminho)

    def tearDown(self):
        self.con.close()
        pathlib.Path(self.caminho).unlink()

    def test_latencia_diaria_agrupa_por_dia(self):
        serie = consultas.latencia_diaria(self.con)
        self.assertEqual(len(serie), 2)
        self.assertEqual(serie[0]["amostras"], 2)
        self.assertEqual(serie[0]["p50"], 10.0)
        self.assertEqual(serie[1]["p50"], 11.0)

    def test_latencia_por_segmento_usa_best(self):
        por_segmento = {d["segmento"]: d for d in consultas.latencia_por_segmento(self.con)}
        self.assertEqual(por_segmento["lan"]["p50"], 0.8)
        self.assertEqual(por_segmento["cgnat"]["p50"], 3.4)
        self.assertIn("destino", por_segmento)

    def test_latencia_por_segmento_ignora_desconhecido(self):
        con = consultas.conectar(construir_banco(
            execucao(BASE_TS, [(1, "_gateway", 0.0, 1.0, 0.8),
                               (2, None, 100.0, 0.0, 0.0),
                               (3, "dns.google", 0.0, 9.0, 8.0)])
        ))
        segmentos = {d["segmento"] for d in consultas.latencia_por_segmento(con)}
        self.assertNotIn("desconhecido", segmentos)
        con.close()

    def test_ultimo_ts(self):
        self.assertEqual(consultas.ultimo_ts(self.con), BASE_TS + UM_DIA + 3600)


class TestClassificacaoDePerda(unittest.TestCase):
    def test_conta_artefato_separado_de_real(self):
        linhas = []
        # Uma execução com perda só no meio: artefato.
        linhas += execucao(BASE_TS, [(1, "_gateway", 0.0, 1.0, 0.8),
                                     (2, "100.70.0.1", 30.0, 4.0, 3.4),
                                     (3, "dns.google", 0.0, 9.0, 8.0)])
        # Uma com perda no destino: real.
        linhas += execucao(BASE_TS + 60, [(1, "_gateway", 0.0, 1.0, 0.8),
                                          (2, "100.70.0.1", 0.0, 4.0, 3.4),
                                          (3, "dns.google", 20.0, 9.0, 8.0)])
        # Uma limpa.
        linhas += execucao(BASE_TS + 120, [(1, "_gateway", 0.0, 1.0, 0.8),
                                           (2, "100.70.0.1", 0.0, 4.0, 3.4),
                                           (3, "dns.google", 0.0, 9.0, 8.0)])
        con = consultas.conectar(construir_banco(linhas))
        contagem = consultas.contagem_de_classificacao(con)
        self.assertEqual(contagem, {"artefato": 1, "real": 1, "sem_perda": 1})
        eventos = consultas.eventos_de_perda(con)
        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["loss_destino"], 20.0)
        con.close()

    def test_classifica_com_filtro_de_tempo(self):
        """Verifica que desde_ts filtra corretamente as execuções antigas."""
        linhas = []
        # Dia 0: sem perda (não será incluída após o corte)
        linhas += execucao(BASE_TS, [(1, "_gateway", 0.0, 1.0, 0.8),
                                     (2, "100.70.0.1", 0.0, 4.0, 3.4),
                                     (3, "dns.google", 0.0, 9.0, 8.0)])
        # Dia 3: perda real (será incluída após o corte)
        linhas += execucao(BASE_TS + 3 * UM_DIA, [(1, "_gateway", 0.0, 1.0, 0.8),
                                                   (2, "100.70.0.1", 0.0, 4.0, 3.4),
                                                   (3, "dns.google", 15.0, 9.0, 8.0)])
        con = consultas.conectar(construir_banco(linhas))

        # Sem filtro: ambas as execuções
        total = consultas.contagem_de_classificacao(con)
        self.assertEqual(total, {"sem_perda": 1, "real": 1})

        # Com filtro a partir do dia 2: apenas a de dia 3
        corte = BASE_TS + 2 * UM_DIA
        recente = consultas.contagem_de_classificacao(con, desde_ts=corte)
        self.assertEqual(recente, {"real": 1})

        con.close()


class TestTraceTruncada(unittest.TestCase):
    """Toda fixture desta suíte era caminho feliz terminando em `dns.google`,
    e por isso nenhum teste percebia que uma trace que parou no gateway era
    medida como se tivesse chegado ao 8.8.8.8. Em 2025-11-30 as 287 execuções
    do dia foram truncadas em 1 hop e o painel plotava 1,24 ms — o dia da
    queda total virava o dia mais rápido da série."""

    def setUp(self):
        linhas = []
        # Dia 0: duas execuções completas, latência 10 ms no destino.
        for n in (0, 1):
            linhas += execucao(BASE_TS + n * 3600, [
                (1, "_gateway", 0.0, 1.0, 0.8),
                (2, "100.70.0.1", 0.0, 4.0, 3.4),
                (3, "dns.google", 0.0, 10.0, 8.0),
            ])
        # Dia 1: a rede caiu. O mtr não passou do gateway e devolveu 1,24 ms
        # com 100% de perda — perda do gateway, não da conexão até o destino.
        linhas += execucao(BASE_TS + UM_DIA, [
            (1, "_gateway", 100.0, 1.24, 1.10),
        ])
        self.caminho = construir_banco(linhas)
        self.con = consultas.conectar(self.caminho)

    def tearDown(self):
        self.con.close()
        pathlib.Path(self.caminho).unlink()

    def test_classifica_como_incompleta(self):
        contagem = consultas.contagem_de_classificacao(self.con)
        self.assertEqual(contagem, {"sem_perda": 2, "incompleta": 1})

    def test_nao_entra_em_eventos_de_perda(self):
        """647 das 1.205 execuções de perda `real` do banco real eram isto."""
        self.assertEqual(consultas.eventos_de_perda(self.con), [])

    def test_nao_contribui_para_latencia_diaria(self):
        """O dia todo truncado some da série em vez de plotar a latência do
        gateway como se fosse a do destino."""
        serie = consultas.latencia_diaria(self.con)
        self.assertEqual([d["dia"] for d in serie], [serie[0]["dia"]])
        self.assertEqual(len(serie), 1)
        self.assertEqual(serie[0]["amostras"], 2)
        self.assertEqual(serie[0]["p50"], 10.0)

    def test_nao_contribui_para_latencia_do_destino_por_segmento(self):
        por_segmento = {
            d["segmento"]: d for d in consultas.latencia_por_segmento(self.con)
        }
        self.assertEqual(por_segmento["destino"]["amostras"], 2)
        self.assertEqual(por_segmento["destino"]["p50"], 8.0)

    def test_nao_contribui_para_a_comparacao_de_baseline(self):
        comparacao = consultas.comparacao_baseline(self.con, dias_janela=7)
        self.assertEqual(comparacao["baseline"]["amostras"], 2)
        self.assertEqual(comparacao["baseline"]["p50"], 10.0)
        self.assertEqual(comparacao["recente"]["amostras"], 2)
        self.assertEqual(comparacao["recente"]["p50"], 10.0)


class TestBaseline(unittest.TestCase):
    def test_compara_janela_recente_com_historico(self):
        linhas = []
        # 20 dias antigos, latência 10. Depois 3 dias recentes, latência 50.
        for dia in range(20):
            linhas += execucao(BASE_TS - (30 - dia) * UM_DIA,
                               [(1, "_gateway", 0.0, 1.0, 0.8),
                                (2, "dns.google", 0.0, 10.0, 9.0)])
        for dia in range(3):
            linhas += execucao(BASE_TS - dia * UM_DIA,
                               [(1, "_gateway", 0.0, 1.0, 0.8),
                                (2, "dns.google", 0.0, 50.0, 45.0)])
        con = consultas.conectar(construir_banco(linhas))
        resultado = consultas.comparacao_baseline(con, dias_janela=7)
        self.assertEqual(resultado["recente"]["p50"], 50.0)
        self.assertEqual(resultado["recente"]["amostras"], 3)
        self.assertEqual(resultado["baseline"]["p50"], 10.0)
        self.assertEqual(resultado["baseline"]["amostras"], 23)
        # Verificar que taxa_perda está presente em ambas (sem perda neste cenário)
        self.assertIsNotNone(resultado["recente"]["taxa_perda"])
        self.assertIsNotNone(resultado["baseline"]["taxa_perda"])
        con.close()

    def test_banco_vazio_devolve_none(self):
        con = consultas.conectar(construir_banco([]))
        self.assertIsNone(consultas.comparacao_baseline(con))
        con.close()


class TestUltimasExecucoes(unittest.TestCase):
    """A seção "Agora": as execuções mais recentes com o detalhe de cada hop.

    O valor da seção é o detalhe por hop — é ele que distingue "a rede caiu" de
    "o seu roteador está a 265 ms perdendo pacote".
    """

    def _banco(self):
        linhas = []
        # Três execuções completas, de 5 em 5 minutos.
        for n in range(3):
            linhas += execucao(BASE_TS + n * 300, [
                (1, "_gateway", 0.0, 1.0, 0.8),
                (2, "100.70.0.1", 0.0, 4.0, 3.4),
                (3, "dns.google", 0.0, 9.0 + n, 8.0),
            ])
        # A mais recente é truncada: morreu no gateway, como na queda real.
        linhas += execucao(BASE_TS + 900, [(1, "_gateway", 90.0, 0.93, 0.9)])
        return construir_banco(linhas)

    def test_devolve_a_mais_recente_primeiro(self):
        con = consultas.conectar(self._banco())
        try:
            execucoes = consultas.ultimas_execucoes(con, limite=4)
            self.assertEqual([e["ts"] for e in execucoes],
                             [BASE_TS + 900, BASE_TS + 600, BASE_TS + 300, BASE_TS])
        finally:
            con.close()

    def test_respeita_o_limite(self):
        con = consultas.conectar(self._banco())
        try:
            self.assertEqual(len(consultas.ultimas_execucoes(con, limite=2)), 2)
        finally:
            con.close()

    def test_cada_execucao_traz_seus_hops_em_ordem(self):
        con = consultas.conectar(self._banco())
        try:
            completa = consultas.ultimas_execucoes(con, limite=4)[1]
            self.assertEqual([h["hop"] for h in completa["detalhe"]], [1, 2, 3])
            self.assertEqual([h["ip"] for h in completa["detalhe"]],
                             ["_gateway", "100.70.0.1", "dns.google"])
        finally:
            con.close()

    def test_trace_truncada_traz_menos_hops_e_vem_marcada(self):
        con = consultas.conectar(self._banco())
        try:
            recente = consultas.ultimas_execucoes(con, limite=1)[0]
            self.assertEqual(len(recente["detalhe"]), 1)
            self.assertEqual(recente["completa"], 0)
            self.assertEqual(recente["classificacao"], "incompleta")
        finally:
            con.close()

    def test_banco_vazio(self):
        con = consultas.conectar(construir_banco([]))
        try:
            self.assertEqual(consultas.ultimas_execucoes(con), [])
        finally:
            con.close()


class TestRota(unittest.TestCase):
    def test_detecta_troca_de_ip_no_hop(self):
        linhas = []
        for dia, ip3 in enumerate(["142.251.200.106", "142.251.200.106", "209.85.173.108"]):
            linhas += execucao(BASE_TS + dia * UM_DIA,
                               [(1, "_gateway", 0.0, 1.0, 0.8),
                                (3, ip3, 0.0, 9.0, 8.0)])
        con = consultas.conectar(construir_banco(linhas))
        trocas = consultas.trocas_de_rota(con)
        self.assertEqual(len(trocas), 1)
        self.assertEqual(trocas[0]["hop"], 3)
        self.assertEqual(trocas[0]["de"], "142.251.200.106")
        self.assertEqual(trocas[0]["para"], "209.85.173.108")
        con.close()

    def test_retorna_trocas_mais_recentes_nao_do_hop_mais_alto(self):
        """Cenário do revisor: trocas em hops diferentes e datas diferentes.

        Sem a correção, truncaria as últimas entradas da lista ordenada por hop,
        perdendo a troca recente do hop 1 em favor das trocas antigas do hop 5.
        """
        linhas = []
        # Dia 0: hop 1 com IP A, hop 5 com IP X
        linhas += execucao(BASE_TS, [(1, "1.1.1.1", 0.0, 1.0, 0.8),
                                     (5, "5.5.5.5", 0.0, 20.0, 18.0)])
        # Dia 1: hop 5 muda para Y (troca antiga)
        linhas += execucao(BASE_TS + UM_DIA, [(1, "1.1.1.1", 0.0, 1.0, 0.8),
                                              (5, "6.6.6.6", 0.0, 20.0, 18.0)])
        # Dia 2: hop 5 muda para Z (mais antiga)
        linhas += execucao(BASE_TS + 2 * UM_DIA, [(1, "1.1.1.1", 0.0, 1.0, 0.8),
                                                   (5, "7.7.7.7", 0.0, 20.0, 18.0)])
        # Dia 3: hop 1 muda de A para B (troca MAIS RECENTE!)
        linhas += execucao(BASE_TS + 3 * UM_DIA, [(1, "2.2.2.2", 0.0, 1.0, 0.8),
                                                   (5, "7.7.7.7", 0.0, 20.0, 18.0)])
        con = consultas.conectar(construir_banco(linhas))

        # Com limite=2, devem vir as 2 trocas mais recentes:
        # 1. Hop 1, dia 3 (mais recente)
        # 2. Hop 5, dia 2 (segunda mais recente)
        trocas = consultas.trocas_de_rota(con, limite=2)
        self.assertEqual(len(trocas), 2)
        # Primeira deve ser a mais recente (hop 1, dia 3)
        self.assertEqual(trocas[0]["hop"], 1)
        self.assertEqual(trocas[0]["de"], "1.1.1.1")
        self.assertEqual(trocas[0]["para"], "2.2.2.2")
        con.close()

    def test_conta_desconhecidos_por_dia(self):
        linhas = execucao(BASE_TS, [(1, "_gateway", 0.0, 1.0, 0.8),
                                    (2, None, 100.0, 0.0, 0.0),
                                    (3, "dns.google", 0.0, 9.0, 8.0)])
        con = consultas.conectar(construir_banco(linhas))
        self.assertEqual(consultas.desconhecidos_por_dia(con)[0]["n"], 1)
        con.close()


if __name__ == "__main__":
    unittest.main()

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
        con.close()

    def test_banco_vazio_devolve_none(self):
        con = consultas.conectar(construir_banco([]))
        self.assertIsNone(consultas.comparacao_baseline(con))
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

    def test_conta_desconhecidos_por_dia(self):
        linhas = execucao(BASE_TS, [(1, "_gateway", 0.0, 1.0, 0.8),
                                    (2, None, 100.0, 0.0, 0.0),
                                    (3, "dns.google", 0.0, 9.0, 8.0)])
        con = consultas.conectar(construir_banco(linhas))
        self.assertEqual(consultas.desconhecidos_por_dia(con)[0]["n"], 1)
        con.close()


if __name__ == "__main__":
    unittest.main()

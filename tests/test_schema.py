"""Testes das views e da classificação de segmento (spec §3.2)."""
import pathlib
import sqlite3
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = RAIZ / "scripts" / "schema.sql"


def banco_em_memoria():
    """Conexão nova com o schema aplicado."""
    con = sqlite3.connect(":memory:")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    return con


def inserir_hop(con, ts, hop, ip, **campos):
    colunas = ["ts", "host", "hop", "ip"] + list(campos)
    valores = [ts, "8.8.8.8", hop, ip] + list(campos.values())
    marcadores = ",".join("?" * len(colunas))
    con.execute(
        f"INSERT INTO mtr_data ({','.join(colunas)}) VALUES ({marcadores})", valores
    )


class TestClassificacaoDeSegmento(unittest.TestCase):
    """A regra de §3.2. Um erro aqui inverte a resposta do Painel 1."""

    CASOS = [
        (1, "_gateway", "lan"),
        (1, "192.168.0.1", "lan"),
        (1, "pfsense.home.arpa", "lan"),
        (4, "10.0.0.1", "lan"),
        (4, "172.16.0.1", "lan"),
        (4, "172.31.255.254", "lan"),
        (2, "100.70.0.1", "cgnat"),
        (2, "100.64.0.1", "cgnat"),
        (2, "100.127.255.1", "cgnat"),
        (3, "142.251.200.106", "transito"),
        (6, "dns.google", "transito"),
        (3, "177-84-70-230.sodobrasil.net.br", "transito"),
        (5, "as15169.riodejaneiro.rj.ix.br", "transito"),
        (2, "100.7.0.1", "transito"),
        (4, "172.15.0.1", "transito"),
        (4, "172.32.0.1", "transito"),
        (2, None, "desconhecido"),
    ]

    def test_cada_endereco_cai_no_segmento_certo(self):
        con = banco_em_memoria()
        for i, (hop, ip, _) in enumerate(self.CASOS):
            inserir_hop(con, 1000 + i, hop, ip)
        obtido = dict(con.execute("SELECT ts, segmento FROM v_hop"))
        for i, (hop, ip, esperado) in enumerate(self.CASOS):
            with self.subTest(ip=ip, hop=hop):
                self.assertEqual(obtido[1000 + i], esperado)

    def test_hostname_publico_nunca_e_lan(self):
        """dns.google aparece 42.662 vezes como destino. Se cair em lan, o
        painel acusa a rede local por latência do Google."""
        con = banco_em_memoria()
        inserir_hop(con, 1, 6, "dns.google")
        self.assertEqual(
            con.execute("SELECT segmento FROM v_hop").fetchone()[0], "transito"
        )


class TestViewRun(unittest.TestCase):
    def test_escolhe_o_hop_de_destino(self):
        con = banco_em_memoria()
        for hop, avg in [(1, 1.0), (2, 3.0), (3, 9.0)]:
            inserir_hop(con, 100, hop, f"h{hop}", avg=avg, loss=0.0)
        self.assertEqual(
            con.execute("SELECT hops, avg FROM v_run").fetchall(), [(3, 9.0)]
        )

    def test_destino_e_por_execucao_nao_global(self):
        """Execuções com número de hops diferente coexistem no banco."""
        con = banco_em_memoria()
        for hop in (1, 2, 3):
            inserir_hop(con, 100, hop, f"h{hop}", avg=float(hop))
        for hop in (1, 2, 3, 4, 5):
            inserir_hop(con, 200, hop, f"h{hop}", avg=float(hop))
        obtido = dict(con.execute("SELECT ts, hops FROM v_run"))
        self.assertEqual(obtido, {100: 3, 200: 5})


class TestViewLoss(unittest.TestCase):
    """A regra de §2.2: 97,4% da perda intermediária é artefato de ICMP."""

    def test_perda_intermediaria_com_destino_limpo_e_artefato(self):
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=0.0)
        inserir_hop(con, 100, 2, "100.70.0.1", loss=20.0)
        inserir_hop(con, 100, 3, "dns.google", loss=0.0)
        linha = con.execute(
            "SELECT loss_destino, loss_intermediaria, classificacao FROM v_loss"
        ).fetchone()
        self.assertEqual(linha, (0.0, 20.0, "artefato"))

    def test_perda_que_chega_ao_destino_e_real(self):
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=0.0)
        inserir_hop(con, 100, 2, "100.70.0.1", loss=20.0)
        inserir_hop(con, 100, 3, "dns.google", loss=10.0)
        linha = con.execute(
            "SELECT loss_destino, classificacao FROM v_loss"
        ).fetchone()
        self.assertEqual(linha, (10.0, "real"))

    def test_perda_apenas_no_destino_e_real(self):
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=0.0)
        inserir_hop(con, 100, 2, "dns.google", loss=30.0)
        self.assertEqual(
            con.execute("SELECT classificacao FROM v_loss").fetchone()[0], "real"
        )

    def test_sem_perda_alguma(self):
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=0.0)
        inserir_hop(con, 100, 2, "dns.google", loss=0.0)
        self.assertEqual(
            con.execute("SELECT classificacao FROM v_loss").fetchone()[0], "sem_perda"
        )


class TestChavePrimaria(unittest.TestCase):
    def test_reinsercao_do_mesmo_hop_e_ignorada(self):
        con = banco_em_memoria()
        for _ in range(3):
            con.execute(
                "INSERT OR IGNORE INTO mtr_data (ts, host, hop, ip) VALUES (?,?,?,?)",
                (100, "8.8.8.8", 1, "_gateway"),
            )
        self.assertEqual(
            con.execute("SELECT COUNT(*) FROM mtr_data").fetchone()[0], 1
        )


if __name__ == "__main__":
    unittest.main()

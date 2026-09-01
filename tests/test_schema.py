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


class TestSegmentoProvedor(unittest.TestCase):
    """Roteador do provedor fora de modo bridge aparece como segundo salto privado.

    Sem separá-lo de `lan`, a barra do painel mistura o equipamento do provedor com o
    do assinante — e como as duas populações têm tamanho parecido, a mediana pousa
    entre elas e não descreve nenhum dos dois.
    """

    def test_segundo_salto_privado_e_do_provedor(self):
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "192.168.5.1")
        inserir_hop(con, 100, 2, "192.168.0.1")
        inserir_hop(con, 100, 3, "bfb34601.virtua.com.br")
        obtido = {h: seg for h, seg in con.execute("SELECT hop, segmento FROM v_hop")}
        self.assertEqual(obtido, {1: "lan", 2: "provedor", 3: "transito"})

    def test_hop_1_continua_lan_mesmo_sendo_privado(self):
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "192.168.5.1")
        self.assertEqual(
            con.execute("SELECT segmento FROM v_hop").fetchone()[0], "lan")

    def test_cgnat_no_hop_2_nao_vira_provedor(self):
        """Em modo bridge o segundo salto é o CGNAT, que não é endereço privado."""
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway")
        inserir_hop(con, 100, 2, "100.70.0.1")
        obtido = {h: seg for h, seg in con.execute("SELECT hop, segmento FROM v_hop")}
        self.assertEqual(obtido, {1: "lan", 2: "cgnat"})

    def test_privado_solto_no_meio_do_caminho_e_lan_nao_provedor(self):
        """Um 192.168 no hop 9 é equipamento local respondendo de dentro do caminho,
        não um segundo nível de NAT."""
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway")
        inserir_hop(con, 100, 2, "100.70.0.1")
        inserir_hop(con, 100, 9, "192.168.5.103")
        self.assertEqual(
            con.execute("SELECT segmento FROM v_hop WHERE hop=9").fetchone()[0], "lan")


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


class TestTraceTruncada(unittest.TestCase):
    """A trace só chegou ao alvo quando o último hop é `transito`.

    Em 753 das 65.341 execuções reais o `mtr` parou antes do 8.8.8.8 e o último
    hop é o roteador do próprio usuário. Sem essa distinção, `v_run` mede o
    gateway e chama de latência até o destino — e 647 dessas execuções entravam
    como perda `real`, 54% do total.
    """

    def test_trace_que_termina_no_transito_e_completa(self):
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=0.0, avg=1.0)
        inserir_hop(con, 100, 2, "100.70.0.1", loss=0.0, avg=4.0)
        inserir_hop(con, 100, 3, "dns.google", loss=0.0, avg=9.0)
        self.assertEqual(
            con.execute("SELECT segmento_destino, completa FROM v_run").fetchone(),
            ("transito", 1),
        )

    def test_trace_que_termina_na_lan_e_incompleta(self):
        """O caso real: 724 execuções cujo último hop é `_gateway`,
        `192.168.0.1` ou `pfsense.home.arpa`."""
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=100.0, avg=1.24, best=1.10)
        self.assertEqual(
            con.execute("SELECT segmento_destino, completa FROM v_run").fetchone(),
            ("lan", 0),
        )

    def test_trace_que_termina_em_desconhecido_e_incompleta(self):
        """29 execuções reais terminam num hop sem resposta (ip NULL)."""
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=0.0, avg=1.0)
        inserir_hop(con, 100, 2, None, loss=100.0, avg=0.0)
        self.assertEqual(
            con.execute("SELECT segmento_destino, completa FROM v_run").fetchone(),
            ("desconhecido", 0),
        )

    def test_trace_que_termina_em_cgnat_e_incompleta(self):
        """Nenhuma execução termina em `cgnat` hoje, mas a regra é escrita pelo
        que é `transito` justamente para que esse caso futuro já conte como
        incompleta em vez de virar exceção esquecida."""
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=0.0, avg=1.0)
        inserir_hop(con, 100, 2, "100.70.0.1", loss=0.0, avg=4.0)
        self.assertEqual(
            con.execute("SELECT segmento_destino, completa FROM v_run").fetchone(),
            ("cgnat", 0),
        )


class TestClassificacaoIncompleta(unittest.TestCase):
    """`incompleta` tem precedência: se a trace não chegou ao destino, não faz
    sentido perguntar se a perda propagou até ele."""

    def test_perda_em_trace_truncada_e_incompleta_nao_real(self):
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=100.0, avg=1.24)
        self.assertEqual(
            con.execute("SELECT classificacao FROM v_loss").fetchone()[0],
            "incompleta",
        )

    def test_trace_truncada_sem_perda_tambem_e_incompleta(self):
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=0.0, avg=1.24)
        inserir_hop(con, 100, 2, "192.168.0.1", loss=0.0, avg=1.5)
        self.assertEqual(
            con.execute("SELECT classificacao FROM v_loss").fetchone()[0],
            "incompleta",
        )

    def test_trace_truncada_com_perda_intermediaria_nao_vira_artefato(self):
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=0.0, avg=1.0)
        inserir_hop(con, 100, 2, None, loss=100.0, avg=0.0)
        inserir_hop(con, 100, 3, "192.168.0.1", loss=0.0, avg=1.5)
        self.assertEqual(
            con.execute("SELECT classificacao FROM v_loss").fetchone()[0],
            "incompleta",
        )

    def test_trace_completa_continua_classificada_pela_propagacao(self):
        """A regra da §2.2 não muda para quem chegou ao destino."""
        con = banco_em_memoria()
        inserir_hop(con, 100, 1, "_gateway", loss=0.0)
        inserir_hop(con, 100, 2, "100.70.0.1", loss=20.0)
        inserir_hop(con, 100, 3, "dns.google", loss=0.0)
        self.assertEqual(
            con.execute("SELECT classificacao FROM v_loss").fetchone()[0],
            "artefato",
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

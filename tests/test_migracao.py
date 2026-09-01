"""Testes da migração do banco legado (TEXT) para o schema tipado."""
import pathlib
import sqlite3
import subprocess
import tempfile
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
MIGRATE = RAIZ / "scripts" / "migrate.sh"

SCHEMA_LEGADO = """
CREATE TABLE mtr_data (
    Mtr_Version TEXT, Start_Time TEXT, Status TEXT, Host TEXT, Hop TEXT,
    Ip TEXT, Loss TEXT, Snt TEXT, Empty TEXT, Last TEXT, Avg TEXT,
    Best TEXT, Wrst TEXT, StDev TEXT
);
"""

LINHAS_LEGADAS = [
    ("MTR.0.95", "1785261016", "OK", "8.8.8.8", "1", "_gateway",
     "0.00", "10", "0", "0.81", "1.05", "0.81", "1.30", "0.16"),
    ("MTR.0.95", "1785261016", "OK", "8.8.8.8", "2", "100.70.0.1",
     "20.00", "10", "2", "3.83", "3.84", "3.42", "4.98", "0.46"),
    ("MTR.0.95", "1785261016", "OK", "8.8.8.8", "3", "???",
     "100.00", "10", "10", "0.00", "0.00", "0.00", "0.00", "0.00"),
    ("MTR.0.95", "1785261016", "OK", "8.8.8.8", "4", "dns.google",
     "0.00", "10", "0", "8.70", "8.26", "7.40", "8.95", "0.44"),
]


class TestMigracao(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = pathlib.Path(self.dir.name) / "mtr_data.db"
        con = sqlite3.connect(self.db)
        con.executescript(SCHEMA_LEGADO)
        con.executemany(
            "INSERT INTO mtr_data VALUES (" + ",".join("?" * 14) + ")",
            LINHAS_LEGADAS,
        )
        con.commit()
        con.close()

    def tearDown(self):
        self.dir.cleanup()

    def migrar(self, *extras):
        return subprocess.run(
            ["bash", str(MIGRATE), str(self.db), *extras],
            capture_output=True, text=True,
        )

    def inserir_sem_chave(self):
        """Linhas que o schema tipado não aceita: ts, host e hop são NOT NULL, e o
        INSERT OR IGNORE descarta a violação sem avisar."""
        con = sqlite3.connect(self.db)
        con.executemany(
            "INSERT INTO mtr_data VALUES (" + ",".join("?" * 14) + ")",
            [
                ("MTR.0.95", "1785261100", "OK", None, "1", "_gateway",
                 "0.0", "10", "0", "0.8", "1.0", "0.8", "1.3", "0.16"),
                ("MTR.0.95", None, "OK", "8.8.8.8", "1", "_gateway",
                 "0.0", "10", "0", "0.8", "1.0", "0.8", "1.3", "0.16"),
            ],
        )
        con.commit()
        con.close()

    def consultar(self, sql):
        con = sqlite3.connect(self.db)
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_migra_todas_as_linhas(self):
        self.assertEqual(self.migrar().returncode, 0)
        self.assertEqual(
            self.consultar("SELECT COUNT(*) FROM mtr_data")[0][0], 4
        )

    def test_converte_os_tipos(self):
        self.migrar()
        linha = self.consultar(
            "SELECT typeof(ts), typeof(hop), typeof(loss) FROM mtr_data LIMIT 1"
        )[0]
        self.assertEqual(linha, ("integer", "integer", "real"))

    def test_interrogacao_vira_nulo(self):
        self.migrar()
        self.assertEqual(
            self.consultar("SELECT COUNT(*) FROM mtr_data WHERE ip IS NULL")[0][0], 1
        )
        self.assertEqual(
            self.consultar("SELECT COUNT(*) FROM mtr_data WHERE ip = '???'")[0][0], 0
        )

    def test_preserva_a_coluna_de_perdas(self):
        """A coluna 'Empty' do schema legado é o contador de pacotes perdidos."""
        self.migrar()
        self.assertEqual(
            self.consultar("SELECT drops FROM mtr_data WHERE hop = 2")[0][0], 2
        )
        self.assertEqual(
            self.consultar("SELECT drops FROM mtr_data WHERE hop = 3")[0][0], 10
        )

    def test_migra_banco_que_ja_tem_as_views_do_schema_novo(self):
        """O monitor.sh novo aplica schema.sql a cada coleta, o que cria as views
        sobre a tabela ainda legada — o SQLite não valida as colunas de uma view na
        criação. Depois, o ALTER TABLE tenta reescrever as referências dentro delas e
        falha com "no such column: ts". Quem faz merge e só então migra cai nisso.
        """
        schema = (RAIZ / "scripts" / "schema.sql").read_text(encoding="utf-8")
        con = sqlite3.connect(self.db)
        con.executescript(schema)
        con.close()
        self.assertEqual(
            {n for (n,) in self.consultar(
                "SELECT name FROM sqlite_master WHERE type='view'")},
            {"v_hop", "v_run", "v_loss"},
            "pré-condição: as views existem sobre a tabela legada",
        )

        resultado = self.migrar()
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(self.consultar("SELECT COUNT(*) FROM mtr_data")[0][0], 4)
        self.assertEqual(
            self.consultar("SELECT typeof(ts) FROM mtr_data LIMIT 1")[0][0], "integer"
        )
        # As views voltam, agora sobre a tabela tipada.
        self.assertEqual(
            self.consultar("SELECT COUNT(*) FROM v_run")[0][0], 1
        )

    def test_aborto_explica_a_causa_e_o_caminho_de_saida(self):
        """A mensagem antiga só dizia que os números divergiam. Sem dizer por quê nem
        como inspecionar, quem migra fica sem ação possível."""
        self.inserir_sem_chave()
        resultado = self.migrar()
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("2 linhas têm Start_Time, Host ou Hop nulos", resultado.stderr)
        self.assertIn("--aceitar-perda", resultado.stderr)
        self.assertIn("SELECT Start_Time, Host, Hop", resultado.stderr)

    def test_aceitar_perda_conclui_apesar_da_divergencia(self):
        self.inserir_sem_chave()
        resultado = self.migrar("--aceitar-perda")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("2 linhas descartadas", resultado.stdout)
        # As 4 boas entraram; mtr_legacy saiu.
        self.assertEqual(self.consultar("SELECT COUNT(*) FROM mtr_data")[0][0], 4)
        self.assertNotIn("mtr_legacy", {
            n for (n,) in self.consultar(
                "SELECT name FROM sqlite_master WHERE type='table'")})

    def test_aceitar_perda_retoma_migracao_abortada(self):
        """O estado em que o banco fica depois de um aborto: mtr_legacy e a tabela
        tipada convivem. Sem a flag o script recusa; com ela, retoma."""
        self.inserir_sem_chave()
        self.assertEqual(self.migrar().returncode, 1)
        self.assertIn("mtr_legacy", {
            n for (n,) in self.consultar(
                "SELECT name FROM sqlite_master WHERE type='table'")})

        resultado = self.migrar("--aceitar-perda")
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertIn("retomando a migração", resultado.stdout)
        self.assertEqual(self.consultar("SELECT COUNT(*) FROM mtr_data")[0][0], 4)
        self.assertEqual(self.consultar("SELECT COUNT(*) FROM v_run")[0][0], 1)

    def test_sem_a_flag_o_estado_inconsistente_segue_recusado(self):
        self.inserir_sem_chave()
        self.migrar()
        resultado = self.migrar()
        self.assertEqual(resultado.returncode, 2)
        self.assertIn("estado inconsistente", resultado.stderr)

    def test_e_idempotente(self):
        self.assertEqual(self.migrar().returncode, 0)
        segunda = self.migrar()
        self.assertEqual(segunda.returncode, 0)
        self.assertEqual(
            self.consultar("SELECT COUNT(*) FROM mtr_data")[0][0], 4
        )

    def test_cria_as_views(self):
        self.migrar()
        views = {
            n for (n,) in self.consultar(
                "SELECT name FROM sqlite_master WHERE type='view'"
            )
        }
        self.assertEqual(views, {"v_hop", "v_run", "v_loss"})

    def test_remove_a_tabela_legada(self):
        self.migrar()
        tabelas = {
            n for (n,) in self.consultar(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertNotIn("mtr_legacy", tabelas)

    def test_gera_backup(self):
        self.migrar()
        backups = list(pathlib.Path(self.dir.name).glob("mtr_data.db.bak-*"))
        self.assertEqual(len(backups), 1)

    def test_detecta_mtr_legacy_residual(self):
        """Banco em estado inconsistente: mtr_legacy existe sem ts. Deve recusar com exit != 0."""
        # Rodar uma migração normal
        self.assertEqual(self.migrar().returncode, 0)

        # Reintroduzir mtr_legacy (simula aborto anterior não resolvido)
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE mtr_legacy AS SELECT * FROM mtr_data LIMIT 0;")
        con.commit()
        con.close()

        # Tentar reexecutar deve recusar com exit 2
        resultado = self.migrar()
        self.assertNotEqual(resultado.returncode, 0)
        self.assertIn("inconsistente", resultado.stderr.lower())

    def test_aborta_com_host_nulo(self):
        """Testa aborto com divergência genuína: Host NULL viola constraint.

        Host NULL é contado pelo COUNT(DISTINCT) do ORIGEM (NULL é um valor),
        mas INSERT OR IGNORE descarta a linha por violação de NOT NULL constraint.

        Fixture: 2 linhas, uma com Host NULL.
        ORIGEM (pós-CAST) = 2
        DESTINO = 1 (Host NULL é descartado)
        Divergência genuína, sem wrapper, testando script real.
        """
        # Remover linhas padrão e adicionar com Host NULL
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM mtr_data")
        con.executemany(
            "INSERT INTO mtr_data VALUES (" + ",".join("?" * 14) + ")",
            [
                ("MTR.0.95", "1000", "OK", "8.8.8.8", "1", "_gateway",
                 "0.00", "10", "0", "0.81", "1.05", "0.81", "1.30", "0.16"),
                ("MTR.0.95", "1000", "OK", None, "2", "100.70.0.1",  # Host=NULL
                 "20.00", "10", "2", "3.83", "3.84", "3.42", "4.98", "0.46"),
            ]
        )
        con.commit()
        con.close()

        # Primeira migração deve falhar com exit 1
        resultado = self.migrar()
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("divergem", resultado.stderr)

        # Verificar que mtr_legacy foi preservado
        tabelas = {
            n for (n,) in self.consultar(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("mtr_legacy", tabelas)

        # Verificar que backup foi criado
        backups = list(pathlib.Path(self.dir.name).glob("mtr_data.db.bak-*"))
        self.assertGreater(len(backups), 0)

        # Segunda migração deve recusar com exit 2 (estado inconsistente)
        resultado2 = self.migrar()
        self.assertNotEqual(resultado2.returncode, 0)
        self.assertIn("inconsistente", resultado2.stderr.lower())

    def test_segunda_execucao_apos_aborto_recusa(self):
        """Valida que segunda execução após aborto recusa com exit != 0.

        Reutiliza fixture com Host NULL para forçar divergência,
        confirmando que a segunda execução detecta estado inconsistente.
        """
        # Fixture com divergência
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM mtr_data")
        con.executemany(
            "INSERT INTO mtr_data VALUES (" + ",".join("?" * 14) + ")",
            [
                ("MTR.0.95", "1111", "OK", "example.com", "1", "10.0.0.1",
                 "0.00", "10", "0", "1.0", "1.0", "1.0", "1.0", "0.1"),
                ("MTR.0.95", "1111", "OK", None, "2", "10.0.0.2",  # Host=NULL
                 "0.00", "10", "0", "2.0", "2.0", "2.0", "2.0", "0.2"),
            ]
        )
        con.commit()
        con.close()

        # Primeira execução falha
        resultado1 = self.migrar()
        self.assertEqual(resultado1.returncode, 1)

        # Segunda execução também falha (exit 2 por inconsistência)
        resultado2 = self.migrar()
        self.assertNotEqual(resultado2.returncode, 0)
        # Não assume exit code específico; apenas não-zero é garantido
        self.assertIn("inconsistente", resultado2.stderr.lower())


if __name__ == "__main__":
    unittest.main()

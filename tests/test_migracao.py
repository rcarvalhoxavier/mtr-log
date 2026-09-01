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

    def migrar(self):
        return subprocess.run(
            ["bash", str(MIGRATE), str(self.db)],
            capture_output=True, text=True,
        )

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


if __name__ == "__main__":
    unittest.main()

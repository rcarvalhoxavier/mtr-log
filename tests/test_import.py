"""Testes do import do monitor.sh: idempotência e tratamento de CSV vazio."""
import pathlib
import sqlite3
import subprocess
import tempfile
import unittest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
MONITOR = RAIZ / "monitor.sh"

CSV = """Mtr_Version,Start_Time,Status,Host,Hop,Ip,Loss%,Snt, ,Last,Avg,Best,Wrst,StDev,
MTR.0.95,1785261016,OK,8.8.8.8,1,_gateway,0.00,10,0,0.81,1.05,0.81,1.30,0.16
MTR.0.95,1785261016,OK,8.8.8.8,2,100.70.0.1,0.00,10,0,3.83,3.84,3.42,4.98,0.46
MTR.0.95,1785261016,OK,8.8.8.8,3,???,100.00,10,10,0.00,0.00,0.00,0.00,0.00
MTR.0.95,1785261016,OK,8.8.8.8,4,dns.google,0.00,10,0,8.70,8.26,7.40,8.95,0.44
"""


class TestImport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.dir.name)
        self.db = self.base / "mtr_data.db"
        self.csv = self.base / "amostra.csv"
        self.csv.write_text(CSV, encoding="utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def rodar_import(self, arquivo, vezes=1):
        """Carrega monitor.sh sem executar main e chama as funções de import."""
        chamadas = "\n".join(["import_data"] * vezes)
        script = f"""
        source '{MONITOR}'
        DB='{self.db}'
        LOG_FILE='{arquivo}'
        setup_database
        {chamadas}
        """
        return subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True
        )

    def contar(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT COUNT(*) FROM mtr_data").fetchone()[0]
        finally:
            con.close()

    def test_importa_as_quatro_linhas(self):
        resultado = self.rodar_import(self.csv)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(self.contar(), 4)

    def test_reimportar_nao_duplica(self):
        """Sem a chave primária, reimportar um CSV duplicava tudo em silêncio."""
        self.rodar_import(self.csv, vezes=3)
        self.assertEqual(self.contar(), 4)

    def test_interrogacao_vira_nulo(self):
        self.rodar_import(self.csv)
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM mtr_data WHERE ip IS NULL"
                ).fetchone()[0],
                1,
            )
        finally:
            con.close()

    def test_csv_vazio_nao_quebra(self):
        """346 dos 65.661 CSVs têm 0 bytes, de execuções em que o mtr falhou."""
        vazio = self.base / "vazio.csv"
        vazio.write_text("", encoding="utf-8")
        resultado = self.rodar_import(vazio)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(self.contar(), 0)

    def test_staging_fica_limpa(self):
        self.rodar_import(self.csv)
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM mtr_raw").fetchone()[0], 0
            )
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()

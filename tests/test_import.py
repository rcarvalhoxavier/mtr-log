"""Testes do import do monitor.sh: idempotência e tratamento de CSV vazio."""
import os
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

CSV_SOBREPOSICAO = """Mtr_Version,Start_Time,Status,Host,Hop,Ip,Loss%,Snt, ,Last,Avg,Best,Wrst,StDev,
MTR.0.95,1785261016,OK,8.8.8.8,1,_gateway,0.00,10,0,0.81,1.05,0.81,1.30,0.16
MTR.0.95,1785261016,OK,8.8.8.8,2,100.70.0.1,0.00,10,0,3.83,3.84,3.42,4.98,0.46
MTR.0.95,1785261016,OK,8.8.8.8,5,novo.host.com,0.00,10,0,5.00,5.50,5.00,6.00,0.50
MTR.0.95,1785261016,OK,8.8.8.8,6,outro.host.com,10.00,10,1,10.00,10.50,10.00,11.00,0.50
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
        """Carrega monitor.sh sem executar main e chama as funções de import.

        O banco vem de MTR_DB, definido ANTES do source. A versão anterior
        atribuía DB depois — e monitor.sh fixava o banco de produção em tempo
        de source, então trocar a ordem destas duas linhas era suficiente para
        a suíte escrever no mtr_data.db real, que o cron alimenta a cada 5
        minutos. Com o override por ambiente, a ordem deixa de importar.
        """
        chamadas = "\n".join(["import_data"] * vezes)
        script = f"""
        export MTR_DB='{self.db}'
        source '{MONITOR}'
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
        resultado = self.rodar_import(self.csv, vezes=3)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(self.contar(), 4)

    def test_sobreposicao_parcial_insere_novos(self):
        """INSERT OR IGNORE permite reimportar CSV com sobreposição parcial.

        Sem OR IGNORE, a statement aborta inteira na primeira colisão de chave.
        Com OR IGNORE, as repetidas são puladas e as novas entram.
        """
        # Importa o CSV original (4 linhas)
        resultado1 = self.rodar_import(self.csv)
        self.assertEqual(resultado1.returncode, 0, resultado1.stderr)
        self.assertEqual(self.contar(), 4)

        # Importa CSV com 2 linhas repetidas (hops 1 e 2) + 2 linhas novas (hops 5 e 6)
        csv_overlapped = self.base / "sobreposicao.csv"
        csv_overlapped.write_text(CSV_SOBREPOSICAO, encoding="utf-8")
        resultado2 = self.rodar_import(csv_overlapped)
        self.assertEqual(resultado2.returncode, 0, resultado2.stderr)

        # Com INSERT OR IGNORE: 4 originais + 2 novos = 6 total
        # Sem INSERT OR IGNORE: statement aborta, continua com 4
        self.assertEqual(self.contar(), 6)

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
        """Só significa alguma coisa se o import tiver de fato terminado bem:
        um .import que falhasse deixaria a staging limpa do mesmo jeito, porque
        o DELETE final rodava mesmo depois do erro."""
        resultado = self.rodar_import(self.csv)
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM mtr_raw").fetchone()[0], 0
            )
        finally:
            con.close()


class TestBancoConfiguravel(unittest.TestCase):
    """Nada impedia a suíte de escrever no banco de produção."""

    def test_mtr_db_definido_antes_do_source_vence(self):
        with tempfile.TemporaryDirectory() as base:
            alvo = pathlib.Path(base) / "descartavel.db"
            resultado = subprocess.run(
                ["bash", "-c", f"export MTR_DB='{alvo}'\nsource '{MONITOR}'\necho \"$DB\""],
                capture_output=True, text=True,
            )
            self.assertEqual(resultado.stdout.strip(), str(alvo))

    def test_sem_mtr_db_o_padrao_continua_o_banco_ao_lado_do_script(self):
        """O override não pode mudar o comportamento em produção, onde o cron
        chama o script sem variável nenhuma. Só lê o valor; não escreve."""
        resultado = subprocess.run(
            ["bash", "-c", f"unset MTR_DB\nsource '{MONITOR}'\necho \"$DB\""],
            capture_output=True, text=True,
        )
        self.assertEqual(resultado.stdout.strip(), str(RAIZ / "mtr_data.db"))


class TestFalhaDeImport(unittest.TestCase):
    """Sem `.bail on`, um .import que falha não interrompe o resto: o INSERT
    seguinte roda e o DELETE final limpa a staging. O cron via sucesso."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.dir.name)
        self.db = self.base / "mtr_data.db"

    def tearDown(self):
        self.dir.cleanup()

    @unittest.skipIf(os.geteuid() == 0, "root lê arquivo sem permissão de leitura")
    def test_csv_ilegivel_devolve_erro_e_nao_promove_nada(self):
        ilegivel = self.base / "ilegivel.csv"
        ilegivel.write_text(CSV, encoding="utf-8")
        ilegivel.chmod(0o000)
        try:
            resultado = subprocess.run(
                ["bash", "-c", f"""
                export MTR_DB='{self.db}'
                source '{MONITOR}'
                LOG_FILE='{ilegivel}'
                setup_database
                import_data
                """],
                capture_output=True, text=True,
            )
        finally:
            ilegivel.chmod(0o644)

        self.assertNotEqual(resultado.returncode, 0, resultado.stdout)
        self.assertIn("falha ao importar", resultado.stderr)
        con = sqlite3.connect(self.db)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM mtr_data").fetchone()[0], 0
            )
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()

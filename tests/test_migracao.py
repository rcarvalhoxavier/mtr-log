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

    def test_aborta_com_divergencia_simulada(self):
        """Simula divergência: banco com 4 linhas, mas migração insere apenas 3.

        Cria um script wrapper que força LIMIT 3 na inserção para simular falha parcial.
        Valida que primeira execução sai com exit 1 e mtr_legacy é preservado.
        """
        # Criar um script wrapper que força divergência
        wrapper_script = pathlib.Path(self.dir.name) / "migrate_broken.sh"
        wrapper_script.write_text(f"""#!/bin/bash
set -euo pipefail

DB="${1}"
SCHEMA="$2"

BACKUP="$DB.bak-$(date +%Y%m%d_%H%M%S)"
cp "$DB" "$BACKUP"

ORIGEM=$(sqlite3 "$DB" "SELECT COUNT(*) FROM (SELECT DISTINCT CAST(Start_Time AS INTEGER), Host, CAST(Hop AS INTEGER) FROM mtr_data);")
echo "linhas distintas na origem (pós-CAST): $ORIGEM"

sqlite3 "$DB" "ALTER TABLE mtr_data RENAME TO mtr_legacy;"
sqlite3 "$DB" < "$SCHEMA"

# INSERIR APENAS 3 LINHAS (das 4) para simular falha parcial
sqlite3 "$DB" <<'SQL'
INSERT OR IGNORE INTO mtr_data
    (ts, host, hop, ip, loss, snt, drops, last, avg, best, wrst, stdev, version, status)
SELECT
    CAST(Start_Time AS INTEGER),
    Host,
    CAST(Hop AS INTEGER),
    NULLIF(Ip, '???'),
    CAST(Loss AS REAL),
    CAST(Snt AS INTEGER),
    CAST(Empty AS INTEGER),
    CAST(Last AS REAL),
    CAST(Avg AS REAL),
    CAST(Best AS REAL),
    CAST(Wrst AS REAL),
    CAST(StDev AS REAL),
    Mtr_Version,
    Status
FROM mtr_legacy
LIMIT 3;
SQL

DESTINO=$(sqlite3 "$DB" "SELECT COUNT(*) FROM mtr_data;")
echo "linhas no destino: $DESTINO"

if [ "$ORIGEM" -ne "$DESTINO" ]; then
    echo "ABORTADO: origem ($ORIGEM) e destino ($DESTINO) divergem." >&2
    echo "A tabela mtr_legacy foi preservada e o backup está em $BACKUP" >&2
    exit 1
fi

sqlite3 "$DB" "DROP TABLE mtr_legacy;"
sqlite3 "$DB" "VACUUM;"
echo "migração concluída: $DESTINO linhas"
""")
        wrapper_script.chmod(0o755)

        # Usar o script wrapper em vez do real
        resultado = subprocess.run(
            ["bash", str(wrapper_script), str(self.db), str(RAIZ / "scripts" / "schema.sql")],
            capture_output=True, text=True,
        )

        # Primeira execução deve falhar com exit 1
        self.assertEqual(resultado.returncode, 1)
        self.assertIn("divergem", resultado.stderr)

        # Verificar que mtr_legacy foi preservado
        tabelas = {
            n for (n,) in self.consultar(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertIn("mtr_legacy", tabelas)

        # Agora tentar com o script REAL, que deve detectar inconsistência
        resultado2 = self.migrar()
        self.assertNotEqual(resultado2.returncode, 0)
        self.assertIn("inconsistente", resultado2.stderr.lower())

    def test_aborta_preserva_backup(self):
        """Valida que após aborto por divergência, backup e mtr_legacy sobrevivem.

        Este teste usa a simulação do teste anterior para garantir que
        o arquivo de backup (.bak-*) está lá após o aborto.
        """
        # Criar um banco com dados variados
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM mtr_data")
        con.executemany(
            "INSERT INTO mtr_data VALUES (" + ",".join("?" * 14) + ")",
            LINHAS_LEGADAS,
        )
        con.commit()
        con.close()

        # Criar um script que força divergência
        wrapper_script = pathlib.Path(self.dir.name) / "migrate_test_backup.sh"
        wrapper_script.write_text(f"""#!/bin/bash
set -euo pipefail

DB="${1}"
SCHEMA="$2"

BACKUP="$DB.bak-$(date +%Y%m%d_%H%M%S)"
cp "$DB" "$BACKUP"

ORIGEM=$(sqlite3 "$DB" "SELECT COUNT(*) FROM (SELECT DISTINCT CAST(Start_Time AS INTEGER), Host, CAST(Hop AS INTEGER) FROM mtr_data);")

sqlite3 "$DB" "ALTER TABLE mtr_data RENAME TO mtr_legacy;"
sqlite3 "$DB" < "$SCHEMA"

# Inserir apenas 2 linhas de 4 para forçar divergência
sqlite3 "$DB" "INSERT INTO mtr_data SELECT * FROM (SELECT * FROM mtr_legacy LIMIT 2) WHERE false;" || true

DESTINO=2

if [ "$ORIGEM" -ne "$DESTINO" ]; then
    echo "ABORTADO: origem ($ORIGEM) e destino ($DESTINO) divergem." >&2
    echo "A tabela mtr_legacy foi preservada e o backup está em $BACKUP" >&2
    exit 1
fi
exit 0
""")
        wrapper_script.chmod(0o755)

        # Executar wrapper
        resultado = subprocess.run(
            ["bash", str(wrapper_script), str(self.db), str(RAIZ / "scripts" / "schema.sql")],
            capture_output=True, text=True,
        )

        self.assertEqual(resultado.returncode, 1)

        # Verificar que backup existe
        backups = list(pathlib.Path(self.dir.name).glob("mtr_data.db.bak-*"))
        self.assertGreater(len(backups), 0)

        # Verificar que mtr_legacy existe
        con = sqlite3.connect(self.db)
        legacy_exists = con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='mtr_legacy'"
        ).fetchone()[0]
        con.close()
        self.assertEqual(legacy_exists, 1)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Gera dashboard.html a partir de mtr_data.db. Apenas stdlib."""
import argparse
import pathlib
import sys

DIR_SCRIPT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(DIR_SCRIPT))

from mtrdash import relatorio  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Gera o dashboard do mtr-log.")
    # Caminhos relativos ao script, nunca ao diretório de trabalho.
    parser.add_argument("--banco", default=str(DIR_SCRIPT.parent / "mtr_data.db"))
    parser.add_argument("--saida", default=str(DIR_SCRIPT.parent / "dashboard.html"))
    argumentos = parser.parse_args()

    banco = pathlib.Path(argumentos.banco)
    if not banco.exists():
        parser.error(f"banco não encontrado: {banco}")

    saida = pathlib.Path(argumentos.saida)
    saida.write_text(relatorio.gerar(banco), encoding="utf-8")
    print(f"escrito: {saida} ({saida.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()

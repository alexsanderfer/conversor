"""
Build de release — USO EXCLUSIVO DO FORNECEDOR.

Faz duas coisas:
  1. Gera o segredo de assinatura (se ainda nao existir) e grava-o em
     _segredo.txt, que NUNCA entra no git.
  2. Gera _segredo_gerado.py com o segredo dentro, para o PyInstaller o
     embutir no .exe. Esse ficheiro tambem nunca entra no git.

O repositorio pode assim ser publicado sem que a protecao deixe de
funcionar, porque o segredo so existe no .exe e no PC do fornecedor.

Uso:
    python build_release.py               # build normal
    python build_release.py --novo-segredo   # GERA UM SEGREDO NOVO
"""

import argparse
import secrets
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).parent
SEGREDO_FILE = RAIZ / "_segredo.txt"
SEGREDO_MOD = RAIZ / "_segredo_gerado.py"
SPEC = RAIZ / "ConversorJumpseller.spec"


def gerar_segredo() -> str:
    """48 caracteres hex (24 bytes) — força bruta irrelevante."""
    return secrets.token_hex(24)


def guardar_segredo(valor: str) -> None:
    SEGREDO_FILE.write_text(valor + "\n", encoding="utf-8")
    SEGREDO_MOD.write_text(
        '"""Gerado por build_release.py. NAO EDITAR. NAO ENVIAR AO CLIENTE."""\n'
        "\n"
        f'SEGREDO = "{valor}"\n',
        encoding="utf-8",
    )
    print(f"Segredo guardado em {SEGREDO_FILE.name} e {SEGREDO_MOD.name}")


def garantir_segredo(novo: bool = False) -> str:
    if novo and SEGREDO_FILE.is_file():
        print(
            "\nAVISO: isto invalida TODAS as licencas ja emitidas.\n"
            "Cada cliente tera de receber uma nova licenca.\n"
        )
        resposta = input("Continua mesmo? (s/N) ")
        if resposta.strip().lower() not in ("s", "sim"):
            print("Cancelado.")
            sys.exit(1)

    if novo or not SEGREDO_FILE.is_file():
        valor = gerar_segredo()
        guardar_segredo(valor)
        print("Segredo NOVO gerado.")
    else:
        valor = SEGREDO_FILE.read_text(encoding="utf-8").strip()
        guardar_segredo(valor)  # regenera o modulo para o build

    return valor


def build() -> int:
    cmd = [
        "uv", "run", "pyinstaller",
        "--clean", "--noconfirm", str(SPEC),
    ]
    print("A correr:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(RAIZ))


def main() -> int:
    ap = argparse.ArgumentParser(description="Build de release do Conversor")
    ap.add_argument(
        "--novo-segredo",
        action="store_true",
        help="Gera um segredo NOVO (invalida as licencas existentes)",
    )
    ap.add_argument(
        "--so-segredo", action="store_true", help="So garante o segredo; nao faz build"
    )
    args = ap.parse_args()

    garantir_segredo(novo=args.novo_segredo)
    if args.so_segredo:
        return 0
    return build()


if __name__ == "__main__":
    raise SystemExit(main())
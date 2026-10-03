"""
Emissor de licenças — USO EXCLUSIVO DO FORNECEDOR.

NUNCA enviar este ficheiro para o cliente e nunca o incluir no build do
PyInstaller. É o que guarda o segredo com que as licenças são assinadas.

Uso:
    # 1. Pedir ao cliente o código da máquina (abre o Conversor e lê o
    #    código que aparece no ecrã de ativação), ou calculá-lo:
    python issue_license.py --fingerprint

    # 2. Emitir a licença
    python issue_license.py "Ferramentas Silva" 12 <machine_id>

O ficheiro .lic resultante é enviado ao cliente, que o arrasta para a
aplicação.
"""

import argparse
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from license_manager import (  # noqa: E402
    SHARED_SECRET,
    compute_machine_fingerprint,
    sign_license,
)


def build_payload(licensee: str, months: int, machine_id: str = "") -> dict:
    issued = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    expires = issued + timedelta(days=int(round(months * 30.4375)))
    return {
        "licensee": licensee,
        "issued": issued.isoformat().replace("+00:00", "Z"),
        "expires": expires.isoformat().replace("+00:00", "Z"),
        "machine_id": machine_id.strip(),
        "nonce": uuid.uuid4().hex,
    }


def issue(licensee: str, months: int, machine_id: str, out_dir: Path) -> Path:
    if not SHARED_SECRET:
        raise SystemExit(
            "Sem segredo de assinatura.\n"
            "Gere um com:  python build_release.py --novo-segredo\n"
            "Ou defina:    $env:CONVERSOR_SEGREDO = '...'\n"
            "Ou grave em:  _segredo.txt"
        )
    payload = build_payload(licensee, months, machine_id)
    out_path = out_dir / f"licenca_{_slug(licensee)}.lic"
    out_path.write_text(sign_license(payload, SHARED_SECRET), encoding="utf-8")
    return out_path


def _slug(text: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "-".join("".join(c if c.isalnum() else " " for c in text).split()).lower()


def main() -> int:
    ap = argparse.ArgumentParser(description="Emite licenças do Conversor Jumpseller")
    ap.add_argument("licensee", nargs="?", help="Nome da loja/cliente")
    ap.add_argument("months", nargs="?", type=int, help="Duração em meses (ex: 12)")
    ap.add_argument("machine_id", nargs="?", help="Código da máquina do cliente")
    ap.add_argument(
        "--fingerprint",
        action="store_true",
        help="Mostra o código desta máquina e sai (use quando o cliente pedir)",
    )
    ap.add_argument(
        "--out", default=".", help="Pasta onde gravar o .lic (default: atual)"
    )
    args = ap.parse_args()

    if args.fingerprint:
        print(f"MachineId: {compute_machine_fingerprint()}")
        return 0

    if not (args.licensee and args.months):
        ap.error("São necessários <licensee> e <months>, ou use --fingerprint")

    machine_id = args.machine_id or ""
    out_path = issue(
        args.licensee, args.months, machine_id, Path(args.out)
    )
    print(f"Licença criada: {out_path}")
    if not machine_id:
        print(
            "AVISO: emitida sem machine_id — funciona em qualquer PC.\n"
            "       Use apenas para testes; para o cliente, passe o código."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

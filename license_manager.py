"""
Gestão de licenças offline do Conversor Jumpseller.

Formato .lic: JSON com chaves ordenadas, separadores canonicals,
assinatura HMAC-SHA256 com segredo partido em 3 fragmentos.

Fingerprint do PC: MachineGuid do Windows (winreg), com fallback
documentado uuid.getnode() (NÃO usado automaticamente na validação).

Estado guardado em %LOCALAPPDATA%/ConversorJumpseller/state.json.
"""

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# SEGREDO DE ASSINATURA
# ---------------------------------------------------------------------------
# O segredo NÃO vive neste ficheiro. Vive em tres sítios, por ordem:
#
#   1. _segredo_gerado.py  — gerado no build, embutido dentro do .exe
#   2. _segredo.txt        — ficheiro local do fornecedor (nunca no git)
#   3. $CONVERSOR_SEGREDO  — variavel de ambiente
#
# Assim o repositorio pode ser publicado sem que a protecao deixe de
# funcionar, e o .exe do cliente continua a conseguir validar licencas.
# Ver build_release.py, que faz a geracao do ponto 1.

_SEGREDO_FILE = Path(__file__).parent / "_segredo.txt"


def _load_secret() -> str:
    # 1. modulo gerado no build (esta e a via dentro do .exe)
    try:
        from _segredo_gerado import SEGREDO  # type: ignore

        if SEGREDO:
            return SEGREDO
    except ImportError:
        pass

    # 2. ficheiro local do fornecedor
    try:
        if _SEGREDO_FILE.is_file():
            texto = _SEGREDO_FILE.read_text(encoding="utf-8").strip()
            if texto:
                return texto
    except OSError:
        pass

    # 3. variavel de ambiente
    return os.environ.get("CONVERSOR_SEGREDO", "").strip()


SHARED_SECRET = _load_secret()

# Nome antigo, mantido para o issue_license.py e para testes antigos.
_SHARED_SECRET = SHARED_SECRET

_STATE_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "ConversorJumpseller"
STATE_FILE = _STATE_DIR / "state.json"

# Clock-rollback guard: tolerância para pequenos ajustes NTP (segundos)
CLOCK_SKEW_TOLERANCE = 120


# ---------------------------------------------------------------------------
# Máquina
# ---------------------------------------------------------------------------

def compute_machine_fingerprint() -> str:
    """Fingerprint SHA-256 do PC (primário = MachineGuid, fallback = MAC)."""
    primary = _machine_guid()
    fallback = str(uuid.getnode())
    return hashlib.sha256(
        (primary + "|" + fallback).encode("utf-8")
    ).hexdigest()


def _machine_guid() -> str:
    try:
        import winreg
    except ImportError:
        return ""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return str(value).strip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Canonicalização + assinatura
# ---------------------------------------------------------------------------

def canonicalize_license_payload(data: dict) -> bytes:
    """Bytes canonicais para assinar/verificar (sem 'signature')."""
    payload = {k: v for k, v in data.items() if k != "signature"}
    return json.dumps(
        payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False
    ).encode("utf-8")


def sign_license(payload: dict, secret: str) -> str:
    """Assina o payload HMAC-SHA256 e devolve o JSON da licença completa."""
    digest = hmac.new(
        secret.encode("utf-8"), canonicalize_license_payload(payload), "sha256"
    ).hexdigest()
    signed = dict(payload)
    signed["signature"] = digest
    return json.dumps(signed, ensure_ascii=False, indent=2)


def _verify_signature(data: dict, secret: str) -> bool:
    if "signature" not in data:
        return False
    expected = data["signature"]
    payload = {k: v for k, v in data.items() if k != "signature"}
    actual = hmac.new(
        secret.encode("utf-8"), canonicalize_license_payload(payload), "sha256"
    ).hexdigest()
    return hmac.compare_digest(expected, actual)


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------

def load_license_state(state_dir: Path | None = None) -> dict:
    state_dir = state_dir or _STATE_DIR
    path = state_dir / "state.json"
    if not path.is_file():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_license_state(state_dir: Path | None = None, data: dict | None = None) -> None:
    state_dir = state_dir or _STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "state.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data or {}, f, ensure_ascii=False, indent=2, sort_keys=True)
    except OSError as exc:
        raise OSError(f"Não foi possível guardar o estado da licença: {exc}")


# ---------------------------------------------------------------------------
# Verificação completa
# ---------------------------------------------------------------------------

def check_license(lic_path: Path, state_dir: Path | None = None, secret: str | None = None) -> tuple[bool, str]:
    """
    Verifica a licença. Devolve (True, "") em buenas condições,
    ou (False, "<motivo em português>").
    """
    secret = secret or SHARED_SECRET
    if not secret:
        return False, (
            "Não foi possível carregar a chave de validação. "
            "Reinstale a aplicação a partir do ficheiro .exe original."
        )
    state_dir = state_dir or _STATE_DIR
    now = datetime.now(timezone.utc)

    # 1. ficheiro existe
    if not lic_path.is_file():
        return False, "Ficheiro de licença não encontrado no caminho guardado. Arraste a licença novamente."

    # 2. JSON válido
    try:
        with open(lic_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False, "Ficheiro de licença inválido (JSON). Obtenha uma nova cópia do fornecedor."

    # 3. assinatura
    if not _verify_signature(data, secret):
        return False, "Ficheiro de licença alterado ou inválido. Obtenha uma nova cópia do fornecedor."

    # 4. machine
    machine_fp = compute_machine_fingerprint()
    lic_machine = (data.get("machine_id") or "").strip()
    if lic_machine and lic_machine != machine_fp:
        return False, "Licença inválida para este computador. O fornecedor deve emitir uma nova licença."

    # 5. validade
    issued_str = (data.get("issued") or "").strip()
    expires_str = (data.get("expires") or "").strip()
    try:
        issued = datetime.fromisoformat(issued_str.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
    except ValueError:
        return False, "Licença com datas inválidas. Obtenha uma nova cópia do fornecedor."

    if now < issued:
        return False, f"Licença ainda não entra em vigor (emite em {issued_str})."
    if now > expires:
        return False, f"Licença expirada em {expires_str}. Contacte o fornecedor para renovação."

    # 6. clock-rollback guard
    state = load_license_state(state_dir)
    max_seen = (state.get("max_seen_time") or "").strip()
    if max_seen:
        try:
            max_seen_dt = datetime.fromisoformat(max_seen.replace("Z", "+00:00"))
            if now < max_seen_dt - timedelta(seconds=CLOCK_SKEW_TOLERANCE):
                return False, (
                    f"Relógio do sistema recuado para antes de {max_seen}. "
                    "Ajuste a data/hora do Windows e reinicie a aplicação."
                )
        except ValueError:
            pass

    # 7. persistir estado
    save_license_state(
        state_dir,
        {
            "license_path": str(lic_path),
            "accepted_at": now.isoformat().replace("+00:00", "Z"),
            "machine_id": machine_fp,
            "max_seen_time": now.isoformat().replace("+00:00", "Z"),
        },
    )
    return True, ""


# ---------------------------------------------------------------------------
# Renovação: limpa estado para forçar nova aceitação
# ---------------------------------------------------------------------------

def clear_license_state(state_dir: Path | None = None) -> None:
    save_license_state(state_dir or _STATE_DIR, {})

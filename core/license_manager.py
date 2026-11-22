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
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# SEGREDO DE ASSINATURA
# ---------------------------------------------------------------------------
# O segredo NÃO vive neste ficheiro, nem no git. Procura em
# tres sítios, por ordem:
#
#   1. _segredo_gerado.py  — gerado no build, embutido no .exe
#   2. ficheiro fora do repo — define CONVERSOR_SECRETDIR com o
#      caminho da pasta que contém _segredo.txt (fornecedor)
#   3. $CONVERSOR_SEGREDO  — variável de ambiente
#
# O ficheiro do fornecedor fica, por exemplo:
#   C:\SegredosConversor\_segredo.txt
# e aponta-se com:
#   set CONVERSOR_SECRETDIR=C:\SegredosConversor
#
# build_release.py gera ambos automaticamente no PC do fornecedor.

_SEGREDO_FILE = Path(os.environ.get(
    "CONVERSOR_SECRETDIR",
    str(Path.home() / "AppData" / "Local" / "ConversorJumpseller"),
)) / "_segredo.txt"


def _load_secret() -> str:
    # 1. modulo gerado no build (dentro do .exe)
    try:
        from _segredo_gerado import SEGREDO  # type: ignore

        if SEGREDO:
            return SEGREDO
    except ImportError:
        pass

    # 2. ficheiro do fornecedor (fora do repo)
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

    # 4. assinatura (chave de ativação)
    if not _verify_signature(data, secret):
        return False, "Chave de ativação inválida. Solicite uma nova chave ao fornecedor."

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
            "max_seen_time": now.isoformat().replace("+00:00", "Z"),
        },
    )
    return True, ""


# ---------------------------------------------------------------------------
# Validação de chave de ativação (formato simples, não-JSON)
# ---------------------------------------------------------------------------

def verify_activation_key(key: str, secret: str | None = None) -> tuple[bool, str]:
    """
    Valida uma chave de ativação (JSON assinado enviado como string).
    A chave pode ser o conteúdo completo do ficheiro .lic ou apenas a string assinada.
    """
    secret = secret or SHARED_SECRET
    if not secret:
        return False, (
            "Não foi possível carregar a chave de validação. "
            "Reinstale a aplicação a partir do ficheiro .exe original."
        )
    if not key or not key.strip():
        return False, "Chave vazia. Insira a chave de ativação enviada pelo fornecedor."

    key = key.strip()

    try:
        data = json.loads(key)
    except (json.JSONDecodeError, ValueError):
        return False, "Formato de chave inválido. A chave deve ser um JSON assinado pelo fornecedor."

    # 1. Verificar assinatura HMAC
    if not _verify_signature(data, secret):
        return False, "Chave de ativação inválida. Solicite uma nova chave ao fornecedor."

    # 2. Validar expiração
    issued_str = (data.get("issued") or "").strip()
    expires_str = (data.get("expires") or "").strip()
    try:
        issued = datetime.fromisoformat(issued_str.replace("Z", "+00:00"))
        expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
    except ValueError:
        return False, "Licença com datas inválidas. Obtenha uma nova cópia do fornecedor."

    now = datetime.now(timezone.utc)
    if now < issued:
        return False, f"Licença ainda não entra em vigor (emite em {issued_str})."
    if now > expires:
        return False, f"Licença expirada em {expires_str}. Contacte o fornecedor para renovação."

    licensee = data.get("licensee", "Cliente")
    return True, f"Chave ativa para: {licensee}"

def clear_license_state(state_dir: Path | None = None) -> None:
    save_license_state(state_dir or _STATE_DIR, {})


def verify_saas_account(email: str, password: str, base_url: str | None = None) -> tuple[bool, str, str | None]:
    """
    Valida uma conta do SaaS via Supabase Auth + perfil de subscrição.

    Faz login com email/senha no Supabase, obtém o perfil do usuário
    e verifica se o plano é Pro ou Lifetime (ativa). Se válido, devolve
    o token de sessão para ser guardado localmente.

    Argumentos:
        email: email da conta SaaS
        password: senha da conta SaaS
        base_url: URL base da API SaaS (default: https://qaazukvxafrwsidiguuo.supabase.co/v1)

    Devolve (True, mensagem) se válida, ou (False, motivo).
    """
    import json

    if not email or not password:
        return False, "Email e senha são obrigatórios."

    base = base_url or "https://qaazukvxafrwsidiguuo.supabase.co"
    # Chave pública anon do Supabase (visível no .env como NEXT_PUBLIC_SUPABASE_ANON_KEY)
    anon_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InFhYXp1a3Z4YWZyd3NpZGlndXVvIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE4MzA3MjcsImV4cCI6MjEwNzQwNjcyN30.w_78NytsvC_3F6JTmTxI-j3P7rGGiMpPqbpdNRPLkBM"

    try:
        import urllib.request

        # 1. Login via Supabase Auth
        # Endpoint correto: /auth/v1/token?grant_type=password
        login_payload = json.dumps({
            "email": email,
            "password": password,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{base}/auth/v1/token?grant_type=password",
            data=login_payload,
            headers={
                "Content-Type": "application/json",
                "apikey": anon_key,
                "Authorization": f"Bearer {anon_key}",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            auth_data = json.loads(resp.read().decode())

        access_token = auth_data.get("access_token")
        user_id = auth_data.get("user", {}).get("id")
        if not access_token or not user_id:
            return False, "Credenciais inválidas. Verifique email e senha."

        # 2. Obter perfil do usuário (tier/subscription)
        profile_req = urllib.request.Request(
            f"{base}/rest/v1/profiles?id=eq.{user_id}&select=tier,full_name,email",
            headers={
                "apikey": anon_key,
                "Authorization": f"Bearer {access_token}",
            },
            method="GET",
        )

        with urllib.request.urlopen(profile_req, timeout=10) as resp:
            profiles = json.loads(resp.read().decode())

        if not profiles:
            return False, "Perfil não encontrado no SaaS."

        profile = profiles[0]
        tier = profile.get("tier", "Free")
        full_name = profile.get("full_name", email)

        # 3. Verificar se o plano está ativo (Pro ou Lifetime)
        valid_tiers = {"Pro", "Lifetime", "pro", "lifetime"}
        if tier not in valid_tiers:
            return False, (
                f"Seu plano '{tier}' não dá direito à ativação do desktop. "
                "Faça upgrade para Pro ou Lifetime no SaaS."
            )

        return True, f"Conta validada: {full_name} ({tier})", tier

    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode()
            data = json.loads(body)
            msg = data.get("message", str(exc))
        except Exception:
            msg = str(exc)
        if exc.code == 401:
            return False, "Email ou senha incorretos."
        return False, f"Erro ao validar conta: {msg}"
    except Exception as exc:
        return False, f"Erro ao contactar o servidor SaaS: {exc}"


def verify_device_code(code: str, base_url: str | None = None) -> tuple[bool, str, str | None]:
    """
    Verifica se um código de dispositivo foi aprovado no SaaS.

    Fluxo Device Code Flow:
    1. Desktop gera código e exibe ao utilizador
    2. Utilizador vai ao navegador e autoriza o dispositivo no SaaS
    3. Desktop consulta este endpoint para verificar se foi aprovado

    Argumentos:
        code: código de ativação do dispositivo
        base_url: URL base da API SaaS (default: https://shopsyncpt.vercel.app/api)

    Devolve (True, mensagem, tier) se aprovado, ou (False, motivo, None).
    """
    import json

    if not code or not code.strip():
        return False, "Código de ativação é obrigatório.", None

    base = base_url or "https://shopsyncpt.vercel.app/api"

    try:
        import urllib.request

        # 1. Consultar servidor se o código foi aprovado
        req = urllib.request.Request(
            f"{base}/device/verify?code={code.strip()}",
            headers={
                "Content-Type": "application/json",
            },
            method="GET",
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        approved = data.get("approved", False)
        if not approved:
            return False, data.get("message", "Código ainda não foi aprovado no SaaS."), None

        tier = data.get("tier", "")
        email = data.get("email", "")

        return True, f"Conta validada: {email} ({tier})", tier

    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, "Código não encontrado ou expirou. Gere um novo código.", None
        if exc.code == 401:
            return False, "Não autorizado. Verifique o código.", None
        try:
            body = exc.read().decode()
            data = json.loads(body)
            msg = data.get("message", str(exc))
        except Exception:
            msg = str(exc)
        return False, f"Erro ao verificar código: {msg}", None
    except Exception as exc:
        return False, f"Erro ao contactar o servidor SaaS: {exc}", None


def check_license_expiry_warning(lic_path: Path) -> str | None:
    """
    Verifica se a licença expira nos próximos 7 dias.
    Devolve uma string de aviso ou None.
    """
    if not lic_path.is_file():
        return None
    try:
        with open(lic_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        expires_str = (data.get("expires") or "").strip()
        if not expires_str:
            return None
        expires = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = expires - now
        days_left = delta.total_seconds() / 86400
        if 0 <= days_left <= 7:
            days_int = max(0, int(days_left))
            return (
                f"Atenção: A sua licença expira em {expires_str} "
                f"(restam {days_int} dias). Contacte o fornecedor para renovação."
            )
    except Exception:
        pass
    return None

"""
Gestor de Releases no Supabase Storage.
Faz o upload do novo binário e remove versões antigas,
mantendo no máximo a versão atual e as 3 versões anteriores (N-3).
"""

import os
import urllib.request
import json
from pathlib import Path

SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL") or os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
BUCKET_NAME = "releases"


def upload_e_limpar_releases(file_path: str, remote_filename: str, max_anteriores: int = 3):
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        print("Aviso: SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY não definidos. Ignorando upload no Supabase Storage.")
        return False

    print(f"A fazer upload de {file_path} para o Supabase Storage (bucket: {BUCKET_NAME})...")

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}/{remote_filename}"

    with open(file_path, "rb") as f:
        file_data = f.read()

    req = urllib.request.Request(
        upload_url,
        data=file_data,
        headers={
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/octet-stream",
            "x-upsert": "true"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            print("Upload concluído com sucesso no Supabase!")
    except Exception as e:
        print(f"Erro no upload para o Supabase: {e}")
        return False

    # Listar ficheiros no bucket para limpeza (manter max_anteriores)
    print("A listar ficheiros no bucket para aplicar política de retenção (N-3)...")
    list_url = f"{SUPABASE_URL}/storage/v1/object/list/{BUCKET_NAME}"

    list_req = urllib.request.Request(
        list_url,
        data=json.dumps({"prefix": "", "limit": 100, "sortBy": {"column": "created_at", "order": "desc"}}).encode("utf-8"),
        headers={
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(list_req) as response:
            files = json.loads(response.read().decode("utf-8"))
            binarios = [f for f in files if f.get("name", "").endswith((".exe", ".zip", ".linux"))]

            print(f"Total de binários no bucket: {len(binarios)}")
            limite = 1 + max_anteriores

            if len(binarios) > limite:
                para_apagar = binarios[limite:]
                print(f"A apagar {len(para_apagar)} versões antigas excedentes...")

                for old_file in para_apagar:
                    name = old_file["name"]
                    print(f"  -> A apagar {name}...")
                    del_url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}"
                    del_req = urllib.request.Request(
                        del_url,
                        data=json.dumps({"prefixes": [name]}).encode("utf-8"),
                        headers={
                            "apikey": SUPABASE_SERVICE_ROLE_KEY,
                            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                            "Content-Type": "application/json"
                        },
                        method="DELETE"
                    )
                    try:
                        urllib.request.urlopen(del_req)
                        print(f"     Apagado com sucesso.")
                    except Exception as del_err:
                        print(f"     Erro ao apagar {name}: {del_err}")
            else:
                print("Nenhum ficheiro antigo para além do limite de retenção.")

    except Exception as list_err:
        print(f"Aviso ao listar/limpar ficheiros do Supabase: {list_err}")

    return True

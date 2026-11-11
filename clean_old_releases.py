"""
Script de limpeza de releases antigos do GitHub.
Mantém apenas a versão mais recente e no máximo as 3 versões anteriores,
apagando todas as outras para economizar espaço e manter o repositório limpo.
"""

import subprocess
import json
import sys


def limpar_releases_antigos(max_anteriores: int = 3):
    print("A listar releases no GitHub...")
    res = subprocess.run(
        ["gh", "release", "list", "--json", "tagName,publishedAt", "-R", "alexsanderfer/conversor"],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        print(f"Erro ao listar releases: {res.stderr}")
        return

    try:
        releases = json.loads(res.stdout)
    except Exception as e:
        print(f"Erro ao interpretar JSON dos releases: {e}")
        return

    # Ordenar por data de publicação (mais recente primeiro)
    releases_ordenados = sorted(releases, key=lambda x: x.get("publishedAt", ""), reverse=True)

    print(f"Total de releases encontrados: {len(releases_ordenados)}")

    # O limite de retenção é: 1 (mais recente) + max_anteriores
    limite = 1 + max_anteriores

    if len(releases_ordenados) <= limite:
        print(f"O número de releases ({len(releases_ordenados)}) está dentro do limite (<= {limite}). Nada a apagar.")
        return

    releases_para_apagar = releases_ordenados[limite:]
    print(f"Releases antigos a apagar ({len(releases_para_apagar)}):")

    for rel in releases_para_apagar:
        tag = rel["tagName"]
        print(f"A apagar release antigo: {tag}...")
        del_res = subprocess.run(
            ["gh", "release", "delete", tag, "--yes", "-R", "alexsanderfer/conversor"],
            capture_output=True,
            text=True,
        )
        if del_res.returncode == 0:
            print(f"  -> Release {tag} apagado com sucesso.")
            subprocess.run(["git", "push", "origin", f":refs/tags/{tag}"], capture_output=True)
        else:
            print(f"  -> Erro ao apagar {tag}: {del_res.stderr}")


if __name__ == "__main__":
    limpar_releases_antigos(3)

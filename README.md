# Conversor Jumpseller

Aplicação Windows que converte o CSV de um fornecedor para o formato de
importação da **Jumpseller**, e actualiza lojas já existentes sem duplicar
produtos.

🌐 **Download:** https://alexsanderfer.github.io/conversor/

---

## O que faz

| Separador | O que faz |
|---|---|
| **Novo ficheiro** | Converte o CSV do fornecedor para o formato de importação da Jumpseller. |
| **Atualizar loja** | Cruza o export da loja com um novo ficheiro do fornecedor. Actualiza produtos existentes pelo SKU, cria os novos, e mantém intactos os que só existem na loja. |

### Regras de negócio

- **Preço** = preço de origem × 1,40 (margem) × 1,23 (IVA)
- **Stock** — `>10` conta como 10; `<5` conta como 0
- **Descrição** — as colunas `desc1`…`desc6` são juntas numa só, com os
  marcadores de lista (`- `, `* `) removidos para o Excel não os interpretar
  como fórmulas
- **Números em formato português** — `1.299,00`, `R$ 45,50` e `45,50 €` são
  lidos correctamente

---

## Requisitos

- Windows 10 ou superior
- Python 3.14 (apenas para correr do código-fonte)

## Instalar e correr

```bash
uv sync --all-extras
uv run python csv_converter_gui.py
```

Na primeira execução aparece o ecrã de licença.

## Testes

```bash
uv run python -m unittest test_license_manager
```

## Build

```bash
python build_release.py
```

Sai em `dist/ConversorJumpseller.exe`.

---

## Licenciamento

Cada instalação é licenciada a **um único computador** durante **12 meses**,
sem necessidade de ligação à internet.

O `.exe` distribui-se pronto a usar; a licença é um ficheiro `.lic` que o
cliente recebe e arrasta para a janela.

> **Nota para o fornecedor.** O segredo de assinatura **não** está neste
> repositório — vive no `.exe` e no PC de quem emite as licenças.
> Para gerar licenças, ver `COMO-GERAR-LICENCAS.md`.

---

## Estrutura

| Ficheiro | Papel |
|---|---|
| `csv_converter_gui.py` | Aplicação principal: conversão, merge, GUI |
| `license_manager.py` | Assinatura HMAC, fingerprint da máquina, validade |
| `license_dialog.py` | Ecrã de activação / renovação |
| `theme.py` | Tema verde (ttk `clam`) e paleta |
| `build_release.py` | Gera o segredo e constrói o `.exe` |
| `test_license_manager.py` | Testes da lógica de licença |

---

© Reservados os direitos de autor e comercialização, é proibida a
reprodução e venda por agente não autorizado.
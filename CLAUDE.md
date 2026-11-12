# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Visão geral

`conversor` é uma aplicação desktop Windows em Python 3.14, baseada em Tkinter, que converte CSVs de fornecedores para o formato de importação da Jumpseller. A aplicação também atualiza uma loja existente por SKU, preservando produtos que só existem na loja e criando ou atualizando os demais.

O fluxo principal de conversão é:

1. `gui/csv_converter_gui.py` lê o CSV, detecta/usa o mapeamento de campos, converte cada linha e grava um CSV separado por `;` com as colunas fixas de `DEST_COLUMNS`.
2. A mesma camada aplica regras de preço, stock, descrição, SKU, categorias, imagens e status.
3. O módulo `core/field_mapping.py` persiste perfis de fornecedor e todas as configurações funcionais em `field_mapping_config.json`, incluindo margem/taxas, prefixo de SKU, idioma, regras de categoria e caminhos recentes.
4. `core/category_classifier.py` mantém regras de classificação por palavras-chave e aprendizagens em `category_classification_rules.json`; essas regras podem preencher categorias quando o fornecedor não as fornece.
5. A GUI também contém o fluxo de atualização da loja, que lê exports com delimitadores/encodings variados, cruza produtos por SKU e grava o estado auxiliar de preços em `_jumpseller_precos.json`.

A maior parte da lógica de domínio ainda está em `gui/csv_converter_gui.py` (`parse_*`, `convert_row`, `process_csv`, atualização da loja e classes Tkinter). Os módulos em `core/` concentram persistência de configuração, licenciamento, atualização, traduções e classificação.

## Estrutura relevante

- `gui/csv_converter_gui.py`: ponto de entrada da aplicação e orquestração da conversão, atualização da loja e GUI.
- `gui/theme.py`: tema, cores e estilos ttk.
- `core/field_mapping.py`: perfis e configurações persistentes; regras de categoria por palavra-chave e mapeamento massivo; normalização e acesso aos valores mapeados.
- `core/category_classifier.py`: classificação automática e aprendizagem de categorias.
- `core/i18n.py`: catálogo de traduções para `pt-PT`, `pt-BR` e `en`; o idioma padrão é `pt-PT`.
- `core/license_manager.py` e `core/license_dialog.py`: licença offline HMAC, fingerprint da máquina, validade e estado em `%LOCALAPPDATA%/ConversorJumpseller`.
- `core/updater.py`: consulta `https://shopsync.pt/api/version` e oferece a página pública de download quando há versão nova.
- `core/stripe_integration.py`: integração usada pela GUI para abrir o checkout.
- `tests/`: testes unitários e de integração; alguns testes exercitam diretamente funções da GUI e outros dependem dos CSVs em `csv_examples/`.
- `CsvFastFileConverter.spec`: configuração do PyInstaller; o executável começa em `gui/csv_converter_gui.py` e empacota `VERSION.txt`, assets e dependências ocultas.
- `build_release.py`: garante o segredo de assinatura, sincroniza `docs/version.txt` e chama o PyInstaller.
- `docs/`: página e arquivos da página pública de download, incluindo `docs/version.txt`.
- `_privado/`: documentação e scripts restritos para emissão de licenças; não é necessário para o desenvolvimento normal.

## Ambiente e comandos

O projeto usa `uv` e declara as dependências em `pyproject.toml`.

```bash
# Instalar/sincronizar dependências, incluindo PyInstaller
uv sync --all-extras

# Executar a aplicação a partir do código-fonte
uv run python gui/csv_converter_gui.py

# Executar toda a suíte unittest
uv run python -m unittest discover -s tests -p "test_*.py" -v

# Executar um módulo unittest específico
uv run python -m unittest tests.test_license_manager -v

# Executar uma classe ou método específico
uv run python -m unittest tests.test_license_manager.TestVerificacao.test_licenca_valida -v

# Executar testes pytest-style que também existem no diretório tests
uv run pytest tests/test_massive_categories.py -q

# Executar um teste pytest específico
uv run pytest tests/test_massive_categories.py::test_massive_category_rule_uses_priority -q

# Build do executável Windows
uv run python build_release.py
```

O `README.md` também documenta `uv run python csv_converter_gui.py` e `python build_release.py`; prefira o prefixo `uv run` para usar o ambiente declarado pelo projeto. Não há configuração de lint/formatador declarada em `pyproject.toml`; não invente um comando de lint sem adicionar/configurar a ferramenta primeiro.

A saída do build é criada em `dist/` pelo PyInstaller. O nome configurado no `.spec` inclui a versão de `VERSION.txt` e a arquitetura (`x64`/`x86`). O build normal também sincroniza `VERSION.txt` para `docs/version.txt`.

## Regras funcionais importantes

- CSVs de entrada da conversão usam `;` e são lidos com `utf-8-sig`.
- A conversão grava `utf-8-sig`, usa `;` e coloca todas as células entre aspas.
- O preço é calculado a partir das configurações do perfil ativo: percentuais de lucro, IVA e portes; há compatibilidade com a configuração antiga `profit_margin`.
- A lógica de stock trata operadores `>` e `<`; o status de saída é `available` quando o stock convertido é maior que zero e `not-available` caso contrário.
- O mapeamento de campos aceita o formato antigo de dicionário plano e o formato atual com `active_profile`, `profiles` e `settings`; não quebre essa migração retrocompatível.
- Regras de categoria têm várias camadas e prioridade: mapeamento massivo, regras por palavras-chave e preservação da hierarquia original. Ao alterar uma camada, verifique os testes em `tests/test_massive_categories.py` e o comportamento de `build_categories`.
- Configurações persistentes ficam fora do código-fonte quando o programa está congelado, normalmente em `%LOCALAPPDATA%/ConversorJumpseller`; em desenvolvimento, vários arquivos de configuração ficam na raiz do projeto ou em `core/`, conforme o módulo.
- O segredo usado para licenças não deve ser criado, exibido ou versionado manualmente. `build_release.py` gera `_segredo.txt` e `_segredo_gerado.py` no ambiente do fornecedor para o PyInstaller embutir o segredo.

## Release e versão

Para alterações de código destinadas a uma release, mantenha a versão sincronizada em:

- `VERSION.txt`;
- `docs/version.txt`;
- `version_info.txt`;
- changelog exibido pela aba Sobre em `gui/csv_converter_gui.py`.

O fluxo de publicação usado neste projeto é buildar o executável e publicar a release correspondente no GitHub com `gh release create`. A release precisa usar o artefato produzido pelo build; `build/` e `dist/` não devem ser commitados. Antes de publicar, verifique o diff, os testes e o estado do repositório. Não use `--novo-segredo` sem autorização explícita, pois isso invalida as licenças já emitidas.

## Testes e limitações locais

Os testes de `core.license_manager` usam um segredo próprio de teste e não dependem do segredo de produção. Testes que criam Tkinter (`test_field_mapping_dialog` em `tests/test_integration.py`) precisam de uma sessão Windows com suporte gráfico. Os testes de conversão que usam arquivos de exemplo precisam dos CSVs em `csv_examples/` e podem alterar configurações persistentes se não isolarem o caminho de configuração; prefira `tmp_path`/diretórios temporários em novos testes.

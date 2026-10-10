# Mapeamento de Campos

O Conversor Jumpseller agora suporta **mapeamento de campos personalizável**, permitindo que você use CSVs com nomes de colunas diferentes dos padrão.

## Como funciona

O conversor usa um arquivo de configuração (`field_mapping_config.json`) que define como cada campo esperado pelo sistema (como `design`, `codigo`, `ref`) deve ser mapeado para uma coluna específica no seu CSV.

## Configuração padrão

Por padrão, o conversor inclui um mapeamento para o CSV `produtos.csv` (exemplo):

```json
{
  "design": "nome",
  "codigo": "codbarras",
  "ref": "referencia",
  "familia_principal": "categoria",
  "sub_familia": "subcategoria",
  "sub_sub_familia": "",
  "desc1": "descricao",
  "desc2": "",
  "desc3": "",
  "desc4": "",
  "desc5": "",
  "desc6": ""
}
```

## Usando a interface gráfica

1. Abra o conversor (`csv_converter_gui.py`)
2. Na aba "Novo ficheiro" ou "Atualizar loja", clique no botão **"Mapear Campos..."**
3. Aparecerá um diálogo com todos os campos mapeáveis
4. Para cada campo esperado (à esquerda), digite o nome da coluna no seu CSV (à direita)
5. Deixe em branco para usar o próprio nome esperado como coluna
6. Clique em **"Save"** para salvar as configurações

## Configuração manual

Você pode editar diretamente o arquivo `field_mapping_config.json` no diretório do projeto:

- **Chave**: Nome do campo esperado pelo conversor (use em `convert_row`)
- **Valor**: Nome real da coluna no seu CSV
- **Valor vazio (`""`)**: Campo opcional que não está presente no CSV

## Campos mapeáveis

| Campo Esperado | Descrição | Exemplo de CSV |
|----------------|-----------|----------------|
| `design` | Nome do produto | `nome` |
| `dimensoes` | Dimensões (L×W×H) | `dimensoes` |
| `codigo` | Código de barras | `codbarras` |
| `ref` | SKU / Referência | `referencia` |
| `peso` | Peso | `peso` |
| `familia_principal` | Categoria principal | `categoria` |
| `sub_familia` | Subcategoria | `subcategoria` |
| `sub_sub_familia` | Sub-subcategoria | (opcional) |
| `desc1` a `desc6` | Campos de descrição | `descricao` |
| `marca` | Marca | `marca` |
| `imagem` | URL da imagem | `imagem` |
| `stock` | Estoque | `stock` |
| `preco` | Preço | `preco` |

## Exemplo de uso

Se o seu CSV tem as seguintes colunas:
```
referencia;nome;descricao;categoria;subcategoria;preco;stock
```

E você quer mapear para o formato Jumpseller, configure:
- `design` → `nome`
- `ref` → `referencia`
- `desc1` → `descricao`
- `familia_principal` → `categoria`
- `sub_familia` → `subcategoria`

## Preservando compatibilidade

Se nenhum mapeamento personalizado estiver configurado, o conversor usa os nomes padrão dos campos (como `design`, `codigo`, etc.), mantendo a compatibilidade com CSVs antigos.

## Arquivo de configuração

O arquivo `field_mapping_config.json` é criado automaticamente na primeira execução e pode ser modificado manualmente ou pela interface gráfica.
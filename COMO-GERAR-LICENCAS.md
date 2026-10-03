# Como gerar licenças — Conversor Jumpseller

Guia de bolso para o **fornecedor** (Alex). Explica como emitir uma licença,
como renovar, e o que **nunca** deve ser enviado ao cliente.

---

## Regra de ouro

> **NUNCA envie `issue_license.py` nem `license_manager.py` para o cliente.**
> O `issue_license.py` é o que guarda o segredo com que as licenças são
> assinadas. Quem tiver esse ficheiro consegue gerar licenças para o que
> quiser. Fica só no seu PC, junto do código-fonte.

O que se envia ao cliente é **apenas** `dist\ConversorJumpseller.exe`.

---

## Fluxo completo (5 minutos)

### Passo 1 — Cliente instala
O cliente recebe o `.exe`, instala e abre. Como ainda não tem licença,
aparece o ecrã verde de ativação com o **código do computador** dele.

```
┌────────────────────────────────────────────┐
│  Este Conversor precisa de uma licença...  │
│                                            │
│  Para receber a licença, envie este código  │
│  ao fornecedor:                            │
│  [1a3157d1ed92c73...3d1db8]  [ Copiar ]   │
└────────────────────────────────────────────┘
```

O cliente clica em **Copiar** e envia-te esse código por email ou WhatsApp.

> Não precisas de calcular nada. O cliente tem o código à mão.
> Só precisas dele se quiseres testar no teu próprio PC.

### Passo 2 — Tu emites a licença
Abre a Powershell na pasta do projeto e corre:

```powershell
python issue_license.py "Nome da Loja" 12 CODIGO_DO_CLIENTE
```

Exemplo real:

```powershell
python issue_license.py "Ferramentas Silva" 12 1a3157d1ed92c73...
```

Sai:

```
Licença criada: C:\...\conversor\licenca_ferramentas-silva.lic
```

O ficheiro `licenca_<nome-da-loja>.lic` fica na pasta atual.

### Passo 3 — Envias a licença
Mandas o `.lic` ao cliente por email ou WhatsApp.

### Passo 4 — Cliente ativa
O cliente arrasta o `.lic` para a janela do programa. Funciona durante 12 meses.

---

## Comandos úteis

| Comando | Para que serve |
|---|---|
| `python issue_license.py --fingerprint` | Código **deste** PC (para testes tu) |
| `python issue_license.py "Loja" 12 CODIGO` | Emite licença de 12 meses |
| `python issue_license.py "Loja" 24 CODIGO` | Emite licença de 2 anos |
| `python issue_license.py "Loja" 12 CODIGO --out C:\licencas` | Grava numa pasta à tua escolha |
| `python issue_license.py --help` | Ajuda |

**Duração em meses:** `12` = 1 ano, `24` = 2 anos, `6` = meio ano. O número é em
meses, não em dias.

---

## Renovação

O cliente avisa que a licença está a acabar (ou já acabou):

1. Pedes-lhe o **código do computador** (se o mesmo PC, é o mesmo código de sempre).
2. Emites uma nova:

```powershell
python issue_license.py "Nome Da Loja" 12 CODIGO
```

3. Envias o novo `.lic`.
4. O cliente arrasta por cima da antiga — substitui.

**Renovar é o mesmo comando.** Não há nada de especial.

---

## Casos especiais

### O cliente mudou de computador
O código muda. Pedes o novo código e emites nova licença com esse código.
É por isso que a licença vale para **um só PC**.

### O cliente formatou o PC
Mesma coisa — o `MachineGuid` do Windows muda quando se reformata.
Pede o código novo e emite outra licença.

### Queres testar sem cliente nenhum
Emite uma licença sem código — funciona em qualquer PC:

```powershell
python issue_license.py "Teste" 12
```

O programa avisa com um `AVISO`. **Só para testes**, nunca para enviar ao cliente.

### Perdi a licença que já enviei ao cliente
Não tem problema. Emitiste com o nome da loja, o `.lic` ficou na pasta onde
correste o comando. Se não a encontrares, emite outra com o mesmo código —
o `.lic` anterior deixa de ser válido, mas como o estado é guardado no PC do
cliente, **manda-lhe o novo e ele arrasta por cima**.

---

## Onde ficam as coisas

| O quê | Onde |
|---|---|
| O `.exe` que envias ao cliente | `dist\ConversorJumpseller.exe` |
| Licenças que emitiste | Onde correste o comando (a pasta atual) |
| Licença ativa no PC do cliente | `%LOCALAPPDATA%\ConversorJumpseller\licenses\conversor.lic` |
| Estado (datas, anti-relógio) | `%LOCALAPPDATA%\ConversorJumpseller\state.json` |

> `%LOCALAPPDATA%` é `C:\Users\<nome-do-utilizador>\AppData\Local`.

---

## Montar o `.exe`

```powershell
uv sync --all-extras
uv run pyinstaller ConversorJumpseller.spec
```

Sai em `dist\ConversorJumpseller.exe`. **Confirma que a data do ficheiro é de hoje**
antes de enviar — o `dist\` pode conter builds antigos.

Ignora `build\` e `ConversorJumpseller.zip`: são ficheiros temporários e
versões antigas. Só o `.exe` interessa.

---

## Testes

```powershell
python -m unittest test_license_manager
```

18 testes. Devem dar `OK`.

---

## Limites da proteção (para saberes o que prometer ao cliente)

- A licença impede **partilhar o programa** e **editar a licença** — resolve o
  problema que o clienteを見ている.
- **Não** impede um-determined attacker de fazer engenharia reversa. O
  segredo está ofuscado no `.exe`, mas quem souber desempacotar pode
  extraí-lo. Para proteção mais forte seria preciso PyArmor (custa mais e
  pode dar problemas de compatibilidade).
- Vale a pena **dizer isto ao cliente** para não haver expectativas erradas.

---

## Erros comuns

| Sintoma | Causa |
|---|---|
| `python: command not found` | Usa `uv run python issue_license.py ...` |
| "Licença inválida para este computador" | O código não é o do PC do cliente |
| "Ficheiro de licença alterado ou inválido" | O `.lic` foi editado à mão |
| "Relógio do sistema recuado" | O cliente mexeu na data do Windows |
| O cliente não vê o ecrã de licença | Já tem licença válida guardada (é normal) |
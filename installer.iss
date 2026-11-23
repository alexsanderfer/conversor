; ============================================================================
; Inno Setup — Instalador do ConversorJumpseller
; ============================================================================
; Gera um instalador Windows para o executável produzido pelo PyInstaller.
;
; A versão e o nome do executável são lidos de VERSION.txt em tempo de
; compilação, por isso o instalador acompanha automaticamente a release.
;
; Uso (linha de comandos):
;   iscc installer.iss
; ou, com o caminho completo do compilador:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
;
; O `build_release.py` invoca o ISCC.exe automaticamente a seguir ao
; PyInstaller, por isso o normal é correr apenas:
;   uv run python build_release.py
;
; Instalação silenciosa (usada pelo sistema de atualização):
;   ConversorJumpseller-Setup-v0.5.14-x64.exe /VERYSILENT /SUPPRESSMSGBOXES
;
; Nota sobre o `SourcePath` do ISPP: neste Inno Setup (6.7.4) o
; `SourcePath` devolve vazio, por isso o script vive na raiz do repositório
; (ao lado de VERSION.txt) e a leitura é feita com caminho relativo simples.
;
; Requisito prévio: o executável tem de existir em dist\ antes de compilar
;   uv run python build_release.py
; ============================================================================

; --- Versão lida de VERSION.txt (contém apenas "v0.5.14") -----------------
; FileRead devolve a linha sem a quebra de linha final. O prefixo "v" é
; removido: o nome do executável de origem mantém "v", mas o VersionInfo
; do Inno Setup só aceita números.
#define VersionHandle
#define RawVersion
#define AppVersionStr
#expr VersionHandle = FileOpen(AddBackslash(SourcePath) + "VERSION.txt")
#if VersionHandle == 0
  #error Não foi possível abrir VERSION.txt
#endif
#expr RawVersion = FileRead(VersionHandle)
#expr FileClose(VersionHandle)
#if RawVersion == ""
  #error Não foi possível ler a versão de VERSION.txt
#endif
#expr AppVersionStr = Copy(RawVersion, 1, 1) == "v" ? Copy(RawVersion, 2) : RawVersion

#define SourceExe "dist\CsvFast-FileConverter-" + RawVersion + "-x64.exe"
#define SetupName "ConversorJumpseller-Setup-" + RawVersion + "-x64"

[Setup]
; --- Identidade da aplicação ---------------------------------------------
AppName=ConversorJumpseller
AppVersion={#AppVersionStr}
AppVerName=ConversorJumpseller {#AppVersionStr}
AppPublisher=Alexsander Fernandes
AppPublisherURL=https://github.com/alexsanderfer/conversor
AppSupportURL=https://shopsync.pt
AppUpdatesURL=https://shopsync.pt

; --- Ficheiros de versão e ícone -----------------------------------------
VersionInfoVersion={#AppVersionStr}
VersionInfoCompany=Alexsander Fernandes
VersionInfoDescription=ConversorJumpseller — Conversor de CSV para Jumpseller
VersionInfoCopyright=© Alexsander Fernandes. Todos os direitos reservados.
VersionInfoProductName=ConversorJumpseller
VersionInfoOriginalFileName=ConversorJumpseller-Setup-{#AppVersionStr}-x64.exe

; --- Destino e permissões ------------------------------------------------
; {commonpf} = Program Files (64 bits) neste build x64.
; PrivilegesRequired=admin: instalação padrão em Program Files, com elevação UAC.
DefaultDirName={commonpf}\ConversorJumpseller
DefaultGroupName=ConversorJumpseller
PrivilegesRequired=admin

; --- Artefacto de saída --------------------------------------------------
OutputDir=dist
OutputBaseFilename={#SetupName}
Compression=lzma2/max
SolidCompression=yes

; --- Ícone e aspeto ------------------------------------------------------
; SetupIconFile é o ícone do próprio assistente; os restantes assets
; (logo/fundo) são copiados para {app}\assets\ e usados pelo assistente.
SetupIconFile=assets\icon.ico
; O executável instalado mantém o "v" da versão (RawVersion), tal como o
; [Files] o copia de SourceExe.
UninstallDisplayIcon={app}\CsvFast-FileConverter-{#RawVersion}-x64.exe
WizardStyle=modern
DisableProgramGroupPage=yes
DisableReadyPage=no

; --- Compatibilidade -----------------------------------------------------
MinVersion=6.1sp1
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Uninstallable=yes
; Fecha a aplicação se estiver aberta (necessário para substituir o exe numa
; atualização). Em modo interativo o Inno Setup avisa o utilizador por omissão
; e pede para fechar; em modo /VERYSILENT fecha sem diálogo, que é o
; comportamento pretendido para a atualização automática.
CloseApplications=yes
RestartApplications=no

; --- Atalhos -------------------------------------------------------------
; O [Files] copia SourceExe mantendo o nome original, que inclui o "v"
; (RawVersion). Por isso atalhos e [Run] usam RawVersion, e nao AppVersionStr.
[Icons]
Name: "{autoprograms}\ConversorJumpseller"; Filename: "{app}\CsvFast-FileConverter-{#RawVersion}-x64.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\ConversorJumpseller"; Filename: "{app}\CsvFast-FileConverter-{#RawVersion}-x64.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

; --- Ficheiros -----------------------------------------------------------
; O build do PyInstaller é "onefile": o exe é autocontido, por isso não há
; pasta internal\ a copiar.
[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; Flags: ignoreversion
; Marcador de versão instalada (base do sistema de atualização).
; Nota: o .spec também embute VERSION.txt no exe onefile; esta cópia em {app}
; serve como marcador legível da versão instalada e é usada pelo updater.
Source: "VERSION.txt"; DestDir: "{app}"; DestName: "VERSION.txt"; Flags: ignoreversion
; Assets usados pelo assistente/instalador (icone, logo e fundo).
Source: "assets\icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "assets\logo.png"; DestDir: "{app}\assets"; Flags: ignoreversion skipifsourcedoesntexist
Source: "assets\fundo.png"; DestDir: "{app}\assets"; Flags: ignoreversion skipifsourcedoesntexist

; --- Arranque opcional ---------------------------------------------------
[Run]
Filename: "{app}\CsvFast-FileConverter-{#RawVersion}-x64.exe"; Description: "{cm:LaunchProgram,ConversorJumpseller}"; Flags: nowait postinstall skipifsilent unchecked

; --- Mensagens em português europeu -------------------------------------
[Languages]
Name: "ptpt"; MessagesFile: "compiler:Languages\Portuguese.isl"

; --- Remoção de instalações anteriores ----------------------------------
; Limpa apenas resíduos de builds antigos (onefile não os produz). Não toca
; em %LOCALAPPDATA%: o estado da licença em
; %LOCALAPPDATA%\ConversorJumpseller\ fica sempre intacto, tanto na
; instalação/atualização como na desinstalação.
[InstallDelete]
Type: filesandordirs; Name: "{app}\internal"
Type: filesandordirs; Name: "{app}\_MEI*"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\internal"


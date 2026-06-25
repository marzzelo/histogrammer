#define AppName      "Histogram FAdeA"
#define AppVersion   "1.3.4"
#define AppPublisher "FAdeA - FÃƒÆ’Ã‚Â¡brica Argentina de Aviones"
#define AppExeName   "HistogramFAdeA.exe"
#define SourceDir    "dist\HistogramFAdeA"

[Setup]
AppId={{E4B2A3C1-7F6D-4E8A-B912-3D5C0F1A2E47}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://www.fadeasa.com.ar
DefaultDirName={autopf}\FAdeA\HistogramFAdeA
DefaultGroupName=FAdeA\Histogram FAdeA
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=HistogramFAdeA_Setup_v{#AppVersion}
SetupIconFile=histogram_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el Escritorio"; GroupDescription: "ÃƒÆ’Ã‚Âconos adicionales:"

[Files]
; Todos los archivos generados por PyInstaller
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; MenÃƒÆ’Ã‚Âº Inicio
Name: "{group}\{#AppName}";     Filename: "{app}\{#AppExeName}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
; Escritorio (opcional, segÃƒÆ’Ã‚Âºn selecciÃƒÆ’Ã‚Â³n del usuario)
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Instalar UCRT en Windows 7 antes de lanzar la aplicaciÃƒÆ’Ã‚Â³n
Filename: "wusa.exe"; Parameters: "{tmp}\Windows6.1-KB2999226-x64.msu /quiet /norestart"; \
  StatusMsg: "Instalando componente del sistema requerido (UCRT)..."; \
  Flags: waituntilterminated; Check: IsWin7
; OpciÃƒÆ’Ã‚Â³n para ejecutar la aplicaciÃƒÆ’Ã‚Â³n al finalizar la instalaciÃƒÆ’Ã‚Â³n
Filename: "{app}\{#AppExeName}"; Description: "Iniciar {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function IsWin7: Boolean;
begin
  Result := (GetWindowsVersion < $06020000);  // menor que Windows 8
end;

[UninstallDelete]
; Eliminar config.ini generado en uso (queda en la carpeta de instalaciÃƒÆ’Ã‚Â³n)
Type: files; Name: "{app}\config.ini"

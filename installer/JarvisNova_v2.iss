; JARVIS NOVA one-click offline installer, 64-bit, no user-side model download.
; This is a build recipe, not an already tested installer.
#define AppVersion "0.4.1-dev"
#if !FileExists("..\dist\JarvisNova\JarvisNova.exe")
  #error Missing compiled GUI EXE
#endif
#if !FileExists("..\dist\JarvisNova\assets\models\base.pt")
  #error Missing Whisper weights
#endif
#if !FileExists("..\dist\JarvisNova\assets\models\v5_ru.pt")
  #error Missing Silero weights
#endif
#if !FileExists("..\dist\JarvisNova\assets\ollama\ollama.exe")
  #error Missing bundled Vision runtime
#endif
#if !FileExists("..\dist\JarvisNova\assets\models\ollama\manifests\registry.ollama.ai\library\qwen3-vl\2b")
  #error Missing Vision model manifest
#endif

[Setup]
AppId={{70BEA90C-8814-4E69-AF2D-BA96986F4F03}
AppName=JARVIS NOVA
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\JarvisNova
DefaultGroupName=JARVIS NOVA
OutputDir=..\dist\installer
OutputBaseFilename=JARVIS-NOVA-OFFLINE-SETUP-DEV
Compression=lzma2/ultra64
SolidCompression=yes
DiskSpanning=no
PrivilegesRequired=lowest
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\JarvisNova.exe
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
SetupLogging=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\JarvisNova\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Icons]
Name: "{autoprograms}\JARVIS NOVA"; Filename: "{app}\JarvisNova.exe"
Name: "{autodesktop}\JARVIS NOVA"; Filename: "{app}\JarvisNova.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\JarvisNova.exe"; Description: "Запустить JARVIS NOVA"; Flags: nowait postinstall skipifsilent

; User settings must live outside {app} to survive updates.

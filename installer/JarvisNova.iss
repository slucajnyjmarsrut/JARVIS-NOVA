; Developer-only Inno Setup 6.5.2+ script. Not proof of a tested release.
#define AppVersion "0.4.0-dev"
#define AppName "JARVIS NOVA"

[Setup]
AppId={{70BEA90C-8814-4E69-AF2D-BA96986F4F03}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=JARVIS NOVA
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

[Files]
Source: "..\dist\JarvisNova\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\JARVIS NOVA"; Filename: "{app}\JarvisNova.exe"
Name: "{autodesktop}\JARVIS NOVA"; Filename: "{app}\JarvisNova.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"

[Run]
Filename: "{app}\JarvisNova.exe"; Description: "Запустить JARVIS NOVA"; Flags: nowait postinstall skipifsilent

; LearningStore lives under the user profile and is not deleted on upgrade/uninstall.

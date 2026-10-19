; ONE offline Inno Setup EXE; refuse compilation if onedir missing.
#define AppVersion "0.5.6-dev"
#define AppName "JARVIS NOVA"
#define AppExecutable "JarvisNova.exe"
#if !FileExists("..\dist\JarvisNova\JarvisNova.exe")
  #error "No complete PyInstaller onedir. Refusing to build empty installer."
#endif

[Setup]
AppId={{70BEA90C-8814-4E69-AF2D-BA96986F4F03}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=JARVIS NOVA
DefaultDirName={localappdata}\Programs\JarvisNova
DefaultGroupName=JARVIS NOVA
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=JARVIS-NOVA-0.5.6-OFFLINE-SETUP-DEV
SetupIconFile=..\assets\jarvis.ico
UninstallDisplayIcon={app}\{#AppExecutable}
Compression=lzma2/ultra64
SolidCompression=yes
DiskSpanning=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
WizardSizePercent=110
DisableWelcomePage=no
CloseApplications=yes
RestartApplications=no
AppMutex=JarvisNovaRuntime
AllowNoIcons=yes
UsePreviousAppDir=yes
ChangesEnvironment=no
ChangesAssociations=no
VersionInfoDescription=JARVIS NOVA Offline Installer (development)
VersionInfoProductName=JARVIS NOVA
VersionInfoVersion=0.5.6.0

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\JarvisNova\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Icons]
Name: "{autoprograms}\JARVIS NOVA"; Filename: "{app}\{#AppExecutable}"
Name: "{autodesktop}\JARVIS NOVA"; Filename: "{app}\{#AppExecutable}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExecutable}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

; User learning data is stored under %LOCALAPPDATA%\JarvisNova, not {app}.
; Upgrading/uninstalling never deletes the user's data folder.

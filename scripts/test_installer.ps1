# Windows runner test of actual Inno installation, real inference and removal.
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Setup = Get-ChildItem (Join-Path $Root 'dist/installer/*.exe') | Select-Object -First 1
if (!$Setup) { throw 'Installer missing' }
$TempRoot = Join-Path $env:RUNNER_TEMP 'JarvisNovaInstallerCheck'
$Target = Join-Path $TempRoot 'JarvisNova'
if (Test-Path $TempRoot) { Remove-Item $TempRoot -Force -Recurse }
New-Item -Path $TempRoot -ItemType Directory -Force | Out-Null
$Data = Join-Path $env:LOCALAPPDATA 'JarvisNova'
New-Item -Path $Data -ItemType Directory -Force | Out-Null
$Sentinel = Join-Path $Data 'inno-uninstall-check.txt'
if (Test-Path $Sentinel) { throw 'Refusing to overwrite an existing user file' }
$Marker = 'JARVIS learning data must survive uninstall'
Set-Content -LiteralPath $Sentinel -Value $Marker -Encoding utf8
try {
    $Arguments = @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR="{0}"' -f $Target))
    $install = Start-Process -FilePath $Setup.FullName -ArgumentList $Arguments -Wait -PassThru -WindowStyle Hidden
    if ($install.ExitCode -ne 0) { throw "Setup failed: $($install.ExitCode)" }
    $Exe=Join-Path $Target 'JarvisNova.exe'
    if (!(Test-Path $Exe)) { throw 'Installed JarvisNova.exe missing' }
    foreach ($Mode in @('--self-test','--video-self-test','--chat-self-test','--real-e2e')) {
        $Run=Start-Process -FilePath $Exe -ArgumentList $Mode -Wait -PassThru -WindowStyle Hidden
        if ($Run.ExitCode -ne 0) { throw "Installed EXE failed ${Mode}: $($Run.ExitCode)" }
    }
    $Uninstall=Join-Path $Target 'unins000.exe'
    if (!(Test-Path $Uninstall)) { throw 'No uninstaller' }
    $remove=Start-Process -FilePath $Uninstall -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') -Wait -PassThru -WindowStyle Hidden
    if ($remove.ExitCode -ne 0) { throw "Uninstall failed: $($remove.ExitCode)" }
    if (Test-Path $Exe) { throw 'Uninstall left JarvisNova.exe' }
    if ((Get-Content -LiteralPath $Sentinel -Raw).Trim() -ne $Marker) { throw 'Uninstall damaged user data' }
    Write-Host 'Installer and real installed Whisper-Vision-Silero E2E passed; learning data survived uninstall'
} finally {
    if (Test-Path $Sentinel) { Remove-Item -LiteralPath $Sentinel -Force }
    if (Test-Path $TempRoot) { Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}

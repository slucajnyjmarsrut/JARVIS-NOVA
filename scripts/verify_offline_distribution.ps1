$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Exe=Join-Path $Root 'dist/JarvisNova/JarvisNova.exe'
if (!(Test-Path $Exe)) { throw 'No built Windows EXE to verify' }
Write-Host 'Running packaged EXE dependency check (NOT real inference)'
$Smoke=Start-Process -FilePath $Exe -ArgumentList '--self-test' -Wait -PassThru -WindowStyle Hidden
if ($Smoke.ExitCode -ne 0) { throw "Packed EXE failed dependency smoke test $($Smoke.ExitCode)" }
Write-Host 'Testing offline Video Studio imports and genuine H.264 MP4 rendering inside EXE'
$Video=Start-Process -FilePath $Exe -ArgumentList '--video-self-test' -Wait -PassThru -WindowStyle Hidden
if ($Video.ExitCode -ne 0) { throw "Packed EXE failed offline video render $($Video.ExitCode)" }
Write-Host 'Testing genuine bundled Qwen offline conversation inside packaged EXE'
$Chat=Start-Process -FilePath $Exe -ArgumentList '--chat-self-test' -Wait -PassThru -WindowStyle Hidden
if ($Chat.ExitCode -ne 0) { throw "Packaged EXE Qwen chat failed $($Chat.ExitCode)" }
Write-Host 'Running packaged EXE with THREE REAL models, synthetic audio/image, no mic/camera'
$E2e=Start-Process -FilePath $Exe -ArgumentList '--real-e2e' -Wait -PassThru -WindowStyle Hidden
if ($E2e.ExitCode -ne 0) { throw "Packed EXE failed real inference $($E2e.ExitCode)" }
Write-Host 'Real model inference passed inside packaged EXE (NOT live hardware E2E)'

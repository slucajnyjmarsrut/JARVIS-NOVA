$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Exe=Join-Path $Root 'dist/JarvisNova/JarvisNova.exe'
if (!(Test-Path $Exe)) { throw 'No built Windows EXE to verify' }
Write-Host 'Checking that the packaged EXE has NO voice models or audio dependencies'
$Smoke=Start-Process -FilePath $Exe -ArgumentList '--self-test' -Wait -PassThru -WindowStyle Hidden
if ($Smoke.ExitCode -ne 0) { throw "Packaged text-only EXE smoke failed $($Smoke.ExitCode)" }
Write-Host 'Testing offline FFmpeg video editing inside packaged EXE'
$Video=Start-Process -FilePath $Exe -ArgumentList '--video-self-test' -Wait -PassThru -WindowStyle Hidden
if ($Video.ExitCode -ne 0) { throw "Packed video renderer failed $($Video.ExitCode)" }
Write-Host 'Testing REAL bundled Qwen offline text conversation'
$Chat=Start-Process -FilePath $Exe -ArgumentList '--chat-self-test' -Wait -PassThru -WindowStyle Hidden
if ($Chat.ExitCode -ne 0) { throw "Packaged Qwen text chat failed $($Chat.ExitCode)" }
Write-Host 'Testing real Qwen Vision on synthetic image, without microphone or speech'
$Vision=Start-Process -FilePath $Exe -ArgumentList '--real-e2e' -Wait -PassThru -WindowStyle Hidden
if ($Vision.ExitCode -ne 0) { throw "Packaged Qwen Vision failed $($Vision.ExitCode)" }
Write-Host 'TEXT-ONLY bundle passed: Qwen chat + Qwen Vision + FFmpeg'

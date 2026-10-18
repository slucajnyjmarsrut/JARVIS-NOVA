# Developer / Windows CI only. End users never install/download Ollama or models.
# Exit on missing trusted SHA-256 for standalone release or missing Vision weights.
param([string]$Tag = 'latest')
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Assets = Join-Path $Root 'assets'
$Dst = Join-Path $Assets 'ollama'
$Models = Join-Path $Assets 'models/ollama'
New-Item -ItemType Directory -Path $Dst,$Models -Force | Out-Null
$Api = 'https://api.github.com/repos/ollama/ollama/releases/' + $(if ($Tag -eq 'latest') { 'latest' } else { 'tags/' + $Tag })
$Release = Invoke-RestMethod -Uri $Api -Headers @{'User-Agent'='Jarvis-Nova-Windows-Build';'Accept'='application/vnd.github+json'}
$Artifact = @($Release.assets) | Where-Object { $_.name -eq 'ollama-windows-amd64.zip' } | Select-Object -First 1
if (!$Artifact) { throw "Portable official ollama-windows-amd64.zip missing from $($Release.tag_name)" }
$Expected = $Artifact.digest
if (!$Expected -or $Expected -notmatch '^sha256:([a-fA-F0-9]{64})$') {
    throw 'Official asset has no published SHA256 digest: cannot verify standalone Ollama archive'
}
$ExpectedHash = $Expected.Substring(7).ToUpperInvariant()
$Zip = Join-Path $env:TEMP 'jarvis-ollama-windows-amd64.zip'
Write-Host "Downloading official standalone Ollama $($Release.tag_name)"
Invoke-WebRequest -Uri $Artifact.browser_download_url -OutFile $Zip
$ActualHash = (Get-FileHash $Zip -Algorithm SHA256).Hash
if ($ActualHash -ne $ExpectedHash) { throw "Portable Ollama zip checksum mismatch, got $ActualHash" }
$TempDir = Join-Path $env:TEMP 'jarvis-ollama-portable-extracted'
if (Test-Path $TempDir) { Remove-Item $TempDir -Recurse -Force }
Expand-Archive -Path $Zip -DestinationPath $TempDir
$OllamaExe = Get-ChildItem $TempDir -Recurse -Filter 'ollama.exe' | Select-Object -First 1
if (!$OllamaExe) { throw 'Official portable archive lacks ollama.exe' }
Copy-Item (Join-Path $OllamaExe.Directory.FullName '*') -Destination $Dst -Recurse -Force
if (!(Test-Path (Join-Path $Dst 'ollama.exe'))) { throw 'Portable runtime copy failed' }
$env:OLLAMA_HOST = '127.0.0.1:21678'
$env:OLLAMA_MODELS = $Models
$env:OLLAMA_NO_CLOUD = '1'
$Server = Start-Process -FilePath (Join-Path $Dst 'ollama.exe') -ArgumentList 'serve' -WindowStyle Hidden -PassThru
try {
    $Ready = $false
    for ($i=0; $i -lt 90; $i++) {
        if ($Server.HasExited) { throw 'Ollama process exited before ready' }
        try {
            Invoke-RestMethod -Uri 'http://127.0.0.1:21678/api/tags' -TimeoutSec 2 | Out-Null
            $Ready=$true;break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (!$Ready) { throw 'Portable Ollama never opened loopback HTTP' }
    Write-Host 'Build-time download of 1.9GB multimodal qwen3-vl:2b-instruct'
    & (Join-Path $Dst 'ollama.exe') pull 'qwen3-vl:2b-instruct'
    if ($LASTEXITCODE -ne 0) { throw 'Ollama pull failed' }
    $Tags=Invoke-RestMethod -Uri 'http://127.0.0.1:21678/api/tags' -TimeoutSec 15
    if (!$Tags.models -or !(@($Tags.models.name) -contains 'qwen3-vl:2b-instruct')) { throw 'Vision model was not registered' }
    $Show = Invoke-RestMethod -Uri 'http://127.0.0.1:21678/api/show' -Method Post -ContentType 'application/json' -Body '{"model":"qwen3-vl:2b-instruct"}'
    if (!(@($Show.capabilities) -contains 'vision')) { throw 'Pulled model does not support vision' }
    Write-Host 'Bundle includes REAL registered qwen3-vl:2b-instruct Vision weights'
} finally {
    if (!$Server.HasExited) { Stop-Process -Id $Server.Id -Force -ErrorAction SilentlyContinue }
}
# The portable official archive includes heavy CUDA GPU runtime DLLs.
# JARVIS NOVA's CPU-only offline Windows installer must stay below 4.2 GB.
# Prune GPU-only libraries; real model inference is retested on CPU AFTER pruning.
$GpuDirPattern = '^(cuda(?:[_-].*)?|rocm(?:[_-].*)?|vulkan(?:[_-].*)?|mlx(?:[_-].*)?|metal(?:[_-].*)?|sycl(?:[_-].*)?|hip(?:[_-].*)?|oneapi(?:[_-].*)?)
    Set-Content -Path (Join-Path $Assets 'BUNDLE_BUILD_INFO.txt') -Encoding utf8

$GpuFilePattern = '^(ggml-(cuda|vulkan|hip|sycl|metal)|cudart|cublas|cudnn|nvrtc|rocblas|amdhip|hipblas)'
$BytesPruned = [long]0
$GpuDirs = @(Get-ChildItem -LiteralPath $Dst -Directory -Recurse | Where-Object { $_.Name -match $GpuDirPattern } | Sort-Object { $_.FullName.Length } -Descending)
foreach ($Dir in $GpuDirs) {
    if (!(Test-Path -LiteralPath $Dir.FullName)) { continue }
    $Length = (Get-ChildItem -LiteralPath $Dir.FullName -File -Recurse | Measure-Object Length -Sum).Sum
    if ($Length) { $BytesPruned += [long]$Length }
    Write-Host "Removing non-CPU Vision runtime directory $($Dir.Name): $Length bytes"
    Remove-Item -LiteralPath $Dir.FullName -Recurse -Force
}
$GpuFiles = @(Get-ChildItem -LiteralPath $Dst -File -Recurse | Where-Object { $_.Name -match $GpuFilePattern })
foreach ($File in $GpuFiles) {
    $BytesPruned += [long]$File.Length
    Write-Host "Removing non-CPU Vision runtime file $($File.Name): $($File.Length) bytes"
    Remove-Item -LiteralPath $File.FullName -Force
}
Write-Host "CPU-only Ollama bundle: removed $BytesPruned GPU bytes (real Vision inference tests MUST now pass)."
"Ollama tag=$($Release.tag_name) archive_sha256=$ActualHash Vision=qwen3-vl:2b-instruct" |
    Set-Content -Path (Join-Path $Assets 'BUNDLE_BUILD_INFO.txt') -Encoding utf8

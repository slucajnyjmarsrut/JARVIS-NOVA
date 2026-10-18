# Download at BUILD TIME, never on an end-user PC. Pinned source and exact SHA256.
$ErrorActionPreference='Stop'
$Root=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ReleaseTag='autobuild-2026-10-18-13-01'
$ArchiveName='ffmpeg-N-127650-geceaa54a38-win64-gpl.zip'
$ExpectedHash='86663EF1F04673CC92C9B18CF7F46BCEF69BDAE14C950435CA6A053792C0B60B'
$DownloadUrl="https://github.com/BtbN/FFmpeg-Builds/releases/download/$ReleaseTag/$ArchiveName"
$Dest=Join-Path $Root 'assets/bin'
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$Zip=Join-Path $env:RUNNER_TEMP $ArchiveName
Invoke-WebRequest -Uri $DownloadUrl -OutFile $Zip
$Actual=(Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash
if ($Actual -ne $ExpectedHash) {throw "FFmpeg SHA-256 mismatch: $Actual"}
$Tmp=Join-Path $env:RUNNER_TEMP 'JarvisFFmpegExtract'
if (Test-Path $Tmp) {Remove-Item -LiteralPath $Tmp -Recurse -Force}
Expand-Archive -LiteralPath $Zip -DestinationPath $Tmp
foreach ($Exe in @('ffmpeg.exe','ffprobe.exe')) {
  $Found=Get-ChildItem -Path $Tmp -Recurse -File -Filter $Exe | Select-Object -First 1
  if (!$Found) {throw "Missing $Exe in FFmpeg archive"}
  Copy-Item -LiteralPath $Found.FullName -Destination (Join-Path $Dest $Exe) -Force
}
$EncoderInfo=& (Join-Path $Dest 'ffmpeg.exe') -hide_banner -encoders 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $EncoderInfo -notmatch '(?m)^\s*V\S*\s+libx264\s') { throw 'Bundled FFmpeg missing H264 libx264 encoder' }
# Captions are composed as transparent PNG overlays. ASS/libass is NOT required.
# Validate only codecs and filters genuinely used by viral_studio.render_video.
$FilterInfo=& (Join-Path $Dest 'ffmpeg.exe') -hide_banner -filters 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $FilterInfo -notmatch '(?m)^\s*[A-Z\.]{3}\s+overlay\s') {
  throw 'Bundled FFmpeg lacks PNG overlay filter'
}
if ($FilterInfo -notmatch '(?m)^\s*[A-Z\.]{3}\s+crop\s' -or
    $FilterInfo -notmatch '(?m)^\s*[A-Z\.]{3}\s+scale\s') {
  throw 'Bundled FFmpeg lacks crop or scale filter'
}
$License=Get-ChildItem -Path $Tmp -Recurse -File | Where-Object { $_.Name -in @('LICENSE','LICENSE.txt','COPYING.LGPLv2.1','COPYING.LGPLv3') } | Select-Object -First 1
if ($License) {Copy-Item -LiteralPath $License.FullName -Destination (Join-Path $Dest 'FFMPEG_LICENSE.txt') -Force}
"FFmpeg build=$ReleaseTag archive=$ArchiveName sha256=$ExpectedHash source=https://github.com/BtbN/FFmpeg-Builds" | Set-Content -Path (Join-Path $Dest 'FFMPEG_BUILD_INFO.txt') -Encoding utf8
Write-Host 'Bundled x64 FFmpeg and FFprobe ready; checksum verified, H264 and PNG overlay filters detected.'

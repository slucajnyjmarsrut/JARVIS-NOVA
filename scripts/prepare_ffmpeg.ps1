# Download FFmpeg at BUILD TIME only, never on an end-user PC.
# BtbN autobuild tags are periodically removed. Resolve a current Windows
# x64 GPL release asset and validate its GitHub-published SHA-256 digest.
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ArchiveName = 'ffmpeg-n8.1-latest-win64-gpl-8.1.zip'
$ReleaseApi = 'https://api.github.com/repos/FFmpeg-Builds/FFmpeg-Builds/releases/tags/latest'
# Query the CURRENT canonical GitHub repository so the Authorization header
# is not dropped across a 301 redirect from the old BtbN repository.
# Use the asset's canonical download URL from the GitHub API. A movable
# "latest" release may point to an underlying autobuild tag.


$Headers = @{
    Accept = 'application/vnd.github+json'
    'User-Agent' = 'JARVIS-NOVA-Windows-CI'
    'X-GitHub-Api-Version' = '2022-11-28'
}
if ($env:GH_TOKEN) {
    $Headers.Authorization = "Bearer $($env:GH_TOKEN)"
}
$Release = Invoke-RestMethod -Uri $ReleaseApi -Headers $Headers -TimeoutSec 60
if ($Release.tag_name -ne 'latest') {
    throw "Unexpected FFmpeg release tag: $($Release.tag_name)"
}
$Candidates = @($Release.assets | Where-Object { $_.name -eq $ArchiveName })
if ($Candidates.Count -ne 1) {
    throw "Expected one Windows x64 GPL FFmpeg archive in the official latest release; found $($Candidates.Count)"
}
$Asset = $Candidates[0]
$DownloadUrl = [string]$Asset.browser_download_url
# This URL comes from GitHub's official BtbN release API. GitHub may
# rewrite repository casing or the moving release tag, so do not require a
# byte-for-byte path. Security is enforced by HTTPS, official host, asset ID
# and most importantly the independently published SHA-256 digest below.
try { $AssetUri = [Uri]$DownloadUrl }
catch { throw 'GitHub supplied an invalid FFmpeg asset URL' }
if (-not $AssetUri.IsAbsoluteUri -or $AssetUri.Scheme -ne 'https' -or
    $AssetUri.Host -ne 'github.com' -or
    $AssetUri.UserInfo -ne '' -or $AssetUri.Query -ne '' -or
    $AssetUri.Fragment -ne '') {
    throw 'GitHub supplied an unsafe FFmpeg asset URL'
}
Write-Host "Official BtbN FFmpeg asset URL: $DownloadUrl"
if ([string]$Asset.digest -cnotmatch '^sha256:[0-9a-f]{64}$') {
    throw 'Official GitHub asset metadata has no valid SHA256 digest'
}
if ([long]$Asset.size -lt 10000000 -or [long]$Asset.size -gt 500000000) {
    throw 'Unexpected FFmpeg archive size in GitHub asset metadata'
}
$ExpectedHash = ([string]$Asset.digest).Substring(7).ToUpperInvariant()
$ReleaseId = [long]$Release.id
$AssetId = [long]$Asset.id

$Dest = Join-Path $Root 'assets/bin'
New-Item -ItemType Directory -Force -Path $Dest | Out-Null
$Zip = Join-Path $env:RUNNER_TEMP $ArchiveName
Invoke-WebRequest -Uri $DownloadUrl -OutFile $Zip -MaximumRedirection 8 -TimeoutSec 900
if ((Get-Item -LiteralPath $Zip).Length -ne [long]$Asset.size) {
    throw 'FFmpeg archive length does not match GitHub asset metadata'
}
$Actual = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash
if ($Actual -ne $ExpectedHash) {
    throw "FFmpeg SHA-256 mismatch: actual=$Actual expected=$ExpectedHash"
}
$Tmp = Join-Path $env:RUNNER_TEMP 'JarvisFFmpegExtract'
if (Test-Path $Tmp) { Remove-Item -LiteralPath $Tmp -Recurse -Force }
Expand-Archive -LiteralPath $Zip -DestinationPath $Tmp
foreach ($Exe in @('ffmpeg.exe','ffprobe.exe')) {
    $Found = Get-ChildItem -Path $Tmp -Recurse -File -Filter $Exe | Select-Object -First 1
    if (!$Found) { throw "Missing $Exe in FFmpeg archive" }
    Copy-Item -LiteralPath $Found.FullName -Destination (Join-Path $Dest $Exe) -Force
}
$EncoderInfo = & (Join-Path $Dest 'ffmpeg.exe') -hide_banner -encoders 2>&1 | Out-String
if ($LASTEXITCODE -ne 0 -or $EncoderInfo -notmatch '(?m)^\s*V\S*\s+libx264\s') {
    throw 'Bundled FFmpeg missing H264 libx264 encoder'
}
# Video Studio burns PNG captions; ASS/libass is not required.
foreach ($Filter in @('overlay','crop','scale','xfade','acrossfade','eq','fade')) {
    $Output = & (Join-Path $Dest 'ffmpeg.exe') -hide_banner -h "filter=$Filter" 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or $Output -notmatch "Filter $Filter") {
        throw "Bundled FFmpeg lacks required filter: $Filter"
    }
}
$License = Get-ChildItem -Path $Tmp -Recurse -File |
    Where-Object { $_.Name -in @('LICENSE','LICENSE.txt','COPYING.LGPLv2.1','COPYING.LGPLv3') } |
    Select-Object -First 1
if ($License) {
    Copy-Item -LiteralPath $License.FullName -Destination (Join-Path $Dest 'FFMPEG_LICENSE.txt') -Force
}
"FFmpeg release_id=$ReleaseId asset_id=$AssetId archive=$ArchiveName sha256=$ExpectedHash source=$DownloadUrl" |
    Set-Content -Path (Join-Path $Dest 'FFMPEG_BUILD_INFO.txt') -Encoding utf8
Write-Host 'Bundled x64 FFmpeg and FFprobe ready; GitHub SHA256 verified, H264 and PNG overlay filters detected.'

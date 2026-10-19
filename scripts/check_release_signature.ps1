# Verify Windows Authenticode chain without suppressing Defender or SmartScreen.
param(
    [Parameter(Mandatory=$true)][string]$Path,
    [switch]$RequireSigned,
    [string]$ExpectedPublisher = ''
)
$ErrorActionPreference = 'Stop'
if (!(Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "Executable missing: $Path"
}
$File = (Resolve-Path -LiteralPath $Path).Path
$Signature = Get-AuthenticodeSignature -LiteralPath $File
if ($Signature.Status -eq 'Valid' -and $null -ne $Signature.SignerCertificate) {
    $Subject = $Signature.SignerCertificate.Subject
    if ($ExpectedPublisher -and
        !$Subject.Contains($ExpectedPublisher, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Publisher mismatch: certificate is $Subject"
    }
    Write-Host "TRUSTED AUTHENTICODE: $([IO.Path]::GetFileName($File))"
    Write-Host "Verified publisher subject: $Subject"
    Write-Host "Certificate thumbprint: $($Signature.SignerCertificate.Thumbprint)"
    if ($env:GITHUB_STEP_SUMMARY) {
        Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value "Verified Authenticode: $([IO.Path]::GetFileName($File)) — $Subject"
    }
} elseif ($RequireSigned) {
    throw "Release BLOCKED: executable is not signed by a Windows-trusted publisher ($($Signature.Status)). Configure Azure Artifact Signing first."
} elseif ($Signature.Status -eq 'NotSigned') {
    Write-Warning "UNSIGNED DEV BUILD: $([IO.Path]::GetFileName($File)). Chrome and SmartScreen may warn. Do not present this as trusted."
    if ($env:GITHUB_STEP_SUMMARY) {
        Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value "UNSIGNED DEVELOPMENT BUILD (not SmartScreen-trusted): $([IO.Path]::GetFileName($File))"
    }
} else {
    throw "Invalid or untrusted Authenticode signature: $($Signature.Status). Refusing to publish."
}

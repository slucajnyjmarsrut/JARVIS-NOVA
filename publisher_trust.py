# -*- coding: utf-8 -*-
"""Pinned Authenticode publisher trust for unattended Windows installers.

A SHA256 checksum from GitHub Releases checks transport integrity, NOT
publisher identity. Windows installation is disabled until the JARVIS NOVA
maintainer adds the SHA256 fingerprint of the vetted code-signing X.509
certificate here, in source, and publishes an Authenticode-signed installer.

Never use environment variables, release text, API JSON, or a model response
as the trust anchor. No remote certificates or alternate pins are accepted.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys

# NOT YET ENROLLED. An empty pin intentionally disables unattended installs.
# Populate ONLY in a reviewed jarvis source commit after validating publisher
# identity, certificate ownership, and Windows Authenticode signing.
PINNED_PUBLISHER_CERT_SHA256 = ""

_SHA256 = re.compile(r"[a-fA-F0-9]{64}\Z")
MAX_CERT_B64 = 32768


class PublisherTrustError(RuntimeError):
    pass


def publisher_is_configured() -> bool:
    return bool(_SHA256.fullmatch(PINNED_PUBLISHER_CERT_SHA256))


def require_publisher_ready() -> None:
    if not publisher_is_configured():
        raise PublisherTrustError(
            "Автоустановка отключена: сертификат издателя JARVIS NOVA "
            "ещё не закреплён. Неподписанный EXE устанавливать нельзя.")


def _read_windows_authenticode_signer(installer: Path) -> bytes:
    """Return signer DER bytes only when Windows validates the EXE signature.

    The command string is static. The file path is supplied through the
    process environment, NOT interpolated into PowerShell source.
    """
    if sys.platform != "win32":
        raise PublisherTrustError("Подпись EXE должна проверяться на Windows.")
    # Determine the trusted Windows system directory through kernel32,
    # never through a user-controlled SystemRoot or PATH variable.
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_system_dir = kernel32.GetSystemDirectoryW
    get_system_dir.argtypes = (ctypes.c_wchar_p, ctypes.c_uint)
    get_system_dir.restype = ctypes.c_uint
    buffer = ctypes.create_unicode_buffer(32768)
    length = get_system_dir(buffer, len(buffer))
    if not (0 < length < len(buffer)):
        raise PublisherTrustError("Невозможно определить системный каталог Windows.")
    powershell = Path(buffer.value) / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file() or powershell.is_symlink():
        raise PublisherTrustError("Системная проверка цифровой подписи недоступна.")
    script = (
        "$ErrorActionPreference='Stop';"
        "$sig=Get-AuthenticodeSignature -LiteralPath $env:JARVIS_NOVA_SIGN_CHECK;"
        "if ($null -eq $sig -or $sig.Status -ne 'Valid' "
        "-or $null -eq $sig.SignerCertificate) { exit 12 };"
        "[Console]::Out.Write([Convert]::ToBase64String("
        "$sig.SignerCertificate.RawData))"
    )
    env = dict(os.environ)
    env["JARVIS_NOVA_SIGN_CHECK"] = str(installer)
    try:
        result = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
             "-Command", script],
            env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=35, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublisherTrustError("Windows не смог проверить подпись установщика.") from exc
    if result.returncode != 0 or len(result.stdout) > MAX_CERT_B64:
        raise PublisherTrustError("Подпись установщика недействительна или не проверена.")
    try:
        certificate = base64.b64decode(result.stdout.strip(), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise PublisherTrustError("Некорректный сертификат подписанта.") from exc
    if not 64 <= len(certificate) <= 16000:
        raise PublisherTrustError("Недопустимый сертификат подписанта.")
    return certificate


def verify_installer_publisher(installer: Path, *, signature_reader=None) -> None:
    """Require Valid Windows Authenticode AND exact pinned signer certificate."""
    require_publisher_ready()
    installer = Path(installer)
    if installer.is_symlink() or not installer.is_file() or installer.suffix.lower() != ".exe":
        raise PublisherTrustError("Проверка издателя требует обычный файл EXE.")
    reader = signature_reader or _read_windows_authenticode_signer
    der = reader(installer)
    if not isinstance(der, bytes) or not 64 <= len(der) <= 16000:
        raise PublisherTrustError("Подпись не вернула действительный сертификат.")
    fingerprint = hashlib.sha256(der).hexdigest()
    if fingerprint != PINNED_PUBLISHER_CERT_SHA256.lower():
        raise PublisherTrustError("Установщик подписан чужим сертификатом издателя.")

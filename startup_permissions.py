# -*- coding: utf-8 -*-
"""Remember *explicit* startup screen/control permissions for a Windows user.

Never grant anything by default. Only an affirmative GUI choice may persist
the two scope flags. A user-scoped Windows DPAPI envelope protects the record
from casual edits/copies; corrupt, legacy or copied settings fail closed.
Neither local model downloads nor external/cloud consent is included.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import stat
import tempfile

SCHEMA = 1
MAX_RECORD_BYTES = 2048
ENTROPY = b"JARVIS-NOVA/permission-scope/control+vision/v1"
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass(frozen=True)
class StartupPermissions:
    control: bool = False
    vision: bool = False


def default_path() -> Path | None:
    root = os.environ.get("LOCALAPPDATA")
    if os.name != "nt" or not root:
        return None
    return Path(root) / "JarvisNova" / "startup_permissions.bin"


def _safe(path: Path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        try:
            meta = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(meta.st_mode) or (
                os.name == "nt" and
                bool(getattr(meta, "st_file_attributes", 0) & _REPARSE)):
            raise OSError("Unsafe permissions file path")


def _dpapi(data: bytes, *, encrypt: bool) -> bytes:
    """CryptProtectData/UnprotectData under current Windows login only."""
    if os.name != "nt":
        raise OSError("Startup permissions are supported only on Windows")
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    def input_blob(value):
        buffer = (ctypes.c_ubyte * max(1, len(value)))()
        if value:
            ctypes.memmove(buffer, value, len(value))
        return Blob(len(value), buffer), buffer

    source, source_buffer = input_blob(data)
    entropy, entropy_buffer = input_blob(ENTROPY)
    output = Blob()
    crypt = ctypes.WinDLL("Crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("Kernel32", use_last_error=True)
    if encrypt:
        api = crypt.CryptProtectData
        api.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR,
                        ctypes.POINTER(Blob), ctypes.c_void_p,
                        ctypes.c_void_p, wintypes.DWORD,
                        ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), "JARVIS NOVA startup permissions",
                ctypes.byref(entropy), None, None, 1, ctypes.byref(output))
    else:
        api = crypt.CryptUnprotectData
        api.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p,
                        ctypes.POINTER(Blob), ctypes.c_void_p,
                        ctypes.c_void_p, wintypes.DWORD,
                        ctypes.POINTER(Blob)]
        args = (ctypes.byref(source), None, ctypes.byref(entropy),
                None, None, 1, ctypes.byref(output))
    api.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not api(*args):
        raise OSError("Windows DPAPI rejected permissions record: "
                      + str(ctypes.get_last_error()))
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))


def load_startup_permissions(path: Path | None = None) -> StartupPermissions:
    """Missing, altered, copied, oversized or legacy settings -> no rights."""
    if os.name != "nt":
        return StartupPermissions()
    path = Path(path) if path is not None else default_path()
    if path is None:
        return StartupPermissions()
    try:
        _safe(path)
        if path.stat().st_size > MAX_RECORD_BYTES:
            return StartupPermissions()
        content = path.read_bytes()
        raw = json.loads(_dpapi(content, encrypt=False))
        if (type(raw) is not dict or raw.get("schema") != SCHEMA or
                raw.get("scope") != "control+vision" or
                raw.get("approved") is not True or
                type(raw.get("control")) is not bool or
                type(raw.get("vision")) is not bool):
            return StartupPermissions()
        return StartupPermissions(raw["control"], raw["vision"])
    except (OSError, ValueError, TypeError, UnicodeError):
        return StartupPermissions()


def save_startup_permissions(perms: StartupPermissions,
                             path: Path | None = None) -> Path:
    """Persist current user's explicit preference, atomically, fail closed."""
    if (type(perms) is not StartupPermissions or
            type(perms.control) is not bool or
            type(perms.vision) is not bool):
        raise ValueError("Invalid startup permissions")
    path = Path(path) if path is not None else default_path()
    if os.name != "nt" or path is None:
        raise OSError("Windows LocalAppData is required")
    _safe(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe(path)
    raw = json.dumps({
        "schema": SCHEMA, "scope": "control+vision", "approved": True,
        "control": perms.control, "vision": perms.vision,
    }, separators=(",", ":")).encode("utf-8")
    sealed = _dpapi(raw, encrypt=True)
    if len(sealed) > MAX_RECORD_BYTES:
        raise OSError("Oversized permissions record")
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent,
                                         prefix=".startup-perms-",
                                         suffix=".tmp", delete=False) as stream:
            tmp = Path(stream.name)
            stream.write(sealed)
            stream.flush()
            os.fsync(stream.fileno())
        _safe(path)
        os.replace(tmp, path)
        return path
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

# -*- coding: utf-8 -*-
"""Bounded local resource protection for the explicitly approved night queue.

Never terminate arbitrary processes, delete files, download models or reboot.
Windows memory measurement uses the kernel's GlobalMemoryStatusEx, not LLM
guesses. Only four fixed, locally installed Ollama specialist models may be unloaded
via loopback Ollama's documented keep_alive=0 API. No redirects or proxies.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import gc
import json
import os
from pathlib import Path
import urllib.request

MIB = 1024 * 1024
MIN_FREE_BYTES = 1100 * MIB
MIN_FREE_FRACTION = 0.12


@dataclass(frozen=True)
class MemorySnapshot:
    available: int
    total: int

    @property
    def minimum(self):
        return max(MIN_FREE_BYTES, int(self.total * MIN_FREE_FRACTION))

    @property
    def low(self):
        return self.available < self.minimum


def _windows_memory():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    api = kernel.GlobalMemoryStatusEx
    api.argtypes = [ctypes.POINTER(MemoryStatus)]
    api.restype = wintypes.BOOL
    if not api(ctypes.byref(status)):
        return None
    return MemorySnapshot(int(status.ullAvailPhys), int(status.ullTotalPhys))


def memory_snapshot():
    """Unsupported/unreadable metrics return None; night run fails closed."""
    if os.name == "nt":
        try:
            return _windows_memory()
        except (OSError, AttributeError, ValueError):
            return None
    try:
        text = Path("/proc/meminfo").read_text(encoding="ascii")
        fields = {}
        for line in text.splitlines():
            key, _, number = line.partition(":")
            if key in ("MemAvailable", "MemTotal"):
                fields[key] = int(number.strip().split()[0]) * 1024
        return MemorySnapshot(fields["MemAvailable"], fields["MemTotal"])
    except (OSError, ValueError, KeyError, IndexError):
        return None


def under_pressure(snapshot):
    """Unknown/corrupt memory metrics must not start a new local model."""
    if not isinstance(snapshot, MemorySnapshot):
        return True
    if (type(snapshot.total) is not int or type(snapshot.available) is not int or
            snapshot.total <= 0 or
            snapshot.available < 0 or snapshot.available > snapshot.total):
        return True
    return snapshot.low


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def _local_unload(model):
    """The URL is hard-coded loopback, not generated or user-controlled."""
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps({"model": model, "prompt": "", "keep_alive": 0,
                         "stream": False}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect())
    with opener.open(request, timeout=4) as response:
        response.read(1024)


def release_specialist_memory(*, sender=None):
    """Best-effort unload four allowlisted Ollama models, no other processes.

    Ollama may be unavailable under OOM: release failures never cause an
    arbitrary kill. GUI/background code may recheck and sleep instead.
    """
    from task_ai_registry import get_specialist
    sender = sender or _local_unload
    ids = {get_specialist(role).model for role in
           ("scenario", "code", "montage", "chat")}
    gc.collect()
    released = 0
    for model in sorted(ids):
        try:
            sender(model)
            released += 1
        except (OSError, ValueError, TypeError, RuntimeError):
            continue
    return released


@contextmanager
def keep_pc_awake():
    """Windows system sleep inhibition for the worker's approved run only."""
    if os.name != "nt":
        yield
        return
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        api = kernel.SetThreadExecutionState
        api.argtypes = [wintypes.DWORD]
        api.restype = wintypes.DWORD
        # CONTINUOUS | SYSTEM_REQUIRED; no DISPLAY_REQUIRED.
        previous = api(0x80000001)
        if not previous:
            raise OSError("SetThreadExecutionState refused request")
    except (OSError, AttributeError, ValueError):
        # The workflow still runs but we do not falsely promise wake-lock.
        previous = 0
        api = None
    try:
        yield
    finally:
        if previous and api is not None:
            api(0x80000000)

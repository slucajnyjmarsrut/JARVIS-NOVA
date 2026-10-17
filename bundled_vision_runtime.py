"""Manage a *bundled*, child-owned portable Windows Ollama vision runtime.

Requires an offline copy of ollama.exe, all its native DLLs and the model store.
Never installs Ollama, downloads models, changes PATH, or connects to the cloud.
Real inference readiness is checked separately by LocalOllamaVision.initialize().
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request


class BundledRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class BundledRuntimeConfig:
    root: Path
    model: str = 'qwen3-vl:2b'
    startup_seconds: float = 45.0


def _model_manifest(models: Path, model: str) -> Path:
    # The local model is not a tag pointer to the public registry at runtime.
    if model != 'qwen3-vl:2b':
        raise BundledRuntimeError('Only the audited qwen3-vl:2b manifest is supported')
    return models / 'manifests' / 'registry.ollama.ai' / 'library' / 'qwen3-vl' / '2b'


def validate_offline_model_store(root: Path, model: str = 'qwen3-vl:2b', *, verify_hashes: bool = False) -> None:
    """Check manifest and local blobs. Hash full weights at BUILD TIME only.

    verify_hashes=True streams every blob to verify official content digests.
    Neither mode establishes that the model can actually process an image.
    """
    models = root / 'models' / 'ollama'
    manifest = _model_manifest(models, model)
    if not manifest.is_file():
        raise BundledRuntimeError(f'Missing offline Vision model manifest: {manifest}')
    try:
        content = json.loads(manifest.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise BundledRuntimeError('Invalid Ollama model manifest JSON') from exc
    descriptors = [content.get('config'), *(content.get('layers') or [])]
    if not descriptors or any(not isinstance(d, dict) for d in descriptors):
        raise BundledRuntimeError('Invalid Ollama model manifest structure')
    for desc in descriptors:
        digest = desc.get('digest', '')
        if not isinstance(digest, str) or len(digest) != 71 or not digest.startswith('sha256:'):
            raise BundledRuntimeError('Invalid model blob digest')
        suffix = digest[7:]
        if any(c not in '0123456789abcdef' for c in suffix):
            raise BundledRuntimeError('Unsafe model blob digest')
        blob = models / 'blobs' / ('sha256-' + suffix)
        if not blob.is_file() or blob.stat().st_size < 1:
            raise BundledRuntimeError(f'Missing model blob: {blob.name}')
        expected_size = desc.get('size')
        if isinstance(expected_size, int) and expected_size != blob.stat().st_size:
            raise BundledRuntimeError(f'Model blob size mismatch: {blob.name}')
        if verify_hashes:
            h = hashlib.sha256()
            with blob.open('rb') as f:
                for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
                    h.update(chunk)
            if h.hexdigest() != suffix:
                raise BundledRuntimeError(f'Model blob SHA256 mismatch: {blob.name}')


class BundledVisionRuntime:
    def __init__(self, config: BundledRuntimeConfig, *, popen=subprocess.Popen):
        self.config = config
        self._popen = popen
        self._proc = None
        self._job = None
        self._port = None

    @property
    def endpoint(self) -> str:
        if self._port is None:
            raise BundledRuntimeError('Bundled runtime has not started')
        return f'http://127.0.0.1:{self._port}'

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _create_windows_job(self, process) -> None:
        """Best-effort Windows job with KILL_ON_JOB_CLOSE for process-tree teardown."""
        if os.name != 'nt':
            return
        from ctypes import wintypes
        class LARGE_INTEGER(ctypes.Structure):
            _fields_ = [('QuadPart', ctypes.c_longlong)]
        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(x, ctypes.c_ulonglong) for x in
                        ('ReadOperationCount','WriteOperationCount','OtherOperationCount',
                         'ReadTransferCount','WriteTransferCount','OtherTransferCount')]
        class BASIC(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', LARGE_INTEGER),
                        ('PerJobUserTimeLimit', LARGE_INTEGER),
                        ('LimitFlags', wintypes.DWORD),
                        ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t),
                        ('ActiveProcessLimit', wintypes.DWORD),
                        ('Affinity', ctypes.c_size_t),
                        ('PriorityClass', wintypes.DWORD),
                        ('SchedulingClass', wintypes.DWORD)]
        class EXTENDED(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', BASIC),('IoInfo', IO_COUNTERS),
                        ('ProcessMemoryLimit', ctypes.c_size_t),
                        ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t),
                        ('PeakJobMemoryUsed', ctypes.c_size_t)]
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateJobObjectW.restype = wintypes.HANDLE
        api.SetInformationJobObject.argtypes = [wintypes.HANDLE,wintypes.INT,ctypes.c_void_p,wintypes.DWORD]
        api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE,wintypes.HANDLE]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        job = api.CreateJobObjectW(None, None)
        if not job:
            raise BundledRuntimeError('Cannot create Windows job object')
        limits = EXTENDED()
        limits.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not api.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            api.CloseHandle(job)
            raise BundledRuntimeError('Cannot secure Windows child process job')
        if not api.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
            api.CloseHandle(job)
            raise BundledRuntimeError('Cannot assign bundled Ollama process to a job')
        self._job = job

    def start(self) -> str:
        if self.running:
            return self.endpoint
        if self._proc is not None:
            self.stop()
        if os.name != 'nt':
            raise BundledRuntimeError('Portable bundled Ollama runtime requires Windows')
        root = self.config.root
        exe = root / 'ollama' / 'ollama.exe'
        if not exe.is_file():
            raise BundledRuntimeError(f'Missing bundled Ollama Windows executable: {exe}')
        validate_offline_model_store(root, self.config.model)
        # Pick an ephemeral free loopback port. Only the process we spawn is used.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(('127.0.0.1', 0))
            port = server.getsockname()[1]
        env = dict(os.environ)
        env.update({
            'OLLAMA_HOST': f'127.0.0.1:{port}',
            'OLLAMA_MODELS': str(root / 'models' / 'ollama'),
            'OLLAMA_NO_CLOUD': '1',
            'OLLAMA_KEEP_ALIVE': '0',
            'OLLAMA_MAX_LOADED_MODELS': '1',
        })
        kwargs = {
            'cwd': str(exe.parent), 'env': env,
            'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
            'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        }
        self._port = port
        try:
            self._proc = self._popen([str(exe), 'serve'], **kwargs)
            self._create_windows_job(self._proc)
            # Test availability without downloading anything.
            deadline = time.monotonic() + self.config.startup_seconds
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    raise BundledRuntimeError('Bundled Ollama exited before becoming ready')
                try:
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(self.endpoint + '/api/tags', timeout=0.8) as response:
                        raw = response.read(65536)
                    if isinstance(json.loads(raw), dict):
                        return self.endpoint
                except (OSError, ValueError, TimeoutError):
                    time.sleep(0.15)
            raise BundledRuntimeError('Bundled Ollama service startup timed out')
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        proc = self._proc
        self._proc = None
        self._port = None
        if self._job is not None:
            if os.name == 'nt':
                ctypes.windll.kernel32.CloseHandle(self._job)
            self._job = None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=4)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass

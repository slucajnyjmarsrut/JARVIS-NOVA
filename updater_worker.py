# -*- coding: utf-8 -*-
"""Separate local updater executable; runs AFTER JARVIS closes.

Every real unattended install rechecks the official release metadata and
the complete SHA256 from GitHub's asset digest. It never executes a remote
script or a non-release installer. If the update fails, retain diagnostics and
the previous app whenever the installer left it intact.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from time import monotonic, sleep

from auto_update import (API_URL, APP_VERSION, Release, UpdateError,
                         _check_download, cache_dir, latest_release,
                         version_tuple)

MAX_INSTALL_SECONDS = 1200


def wait_for_parent(pid: int, *, timeout=90) -> None:
    if type(pid) is not int or pid<=0 or pid==os.getpid():
        raise UpdateError("Недопустимый идентификатор приложения")
    if os.name!="nt":
        raise UpdateError("Обновления поддерживаются только на Windows")
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD)
    kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.OpenProcess(0x00100000,False,pid)  # SYNCHRONIZE, no termination
    if not handle:
        # Process may have exited already. Other errors fail closed.
        err=ctypes.get_last_error()
        if err==87:  # ERROR_INVALID_PARAMETER (no such process)
            return
        raise UpdateError(f"Не удалось дождаться завершения приложения: {err}")
    try:
        result=kernel.WaitForSingleObject(handle,max(1000,int(timeout*1000)))
        if result!=0:  # WAIT_TIMEOUT or WAIT_FAILED: never install
            raise UpdateError("JARVIS всё ещё работает; обновление отложено")
    finally:
        kernel.CloseHandle(handle)


def record_status(folder: Path, status: str, version: str, reason: str="") -> None:
    # No user texts, voice or file paths in diagnostic status.
    data={"status":status,"version":version,"reason":reason[:140]}
    fd,name=tempfile.mkstemp(prefix=".update-",suffix=".json",dir=str(folder))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False)
            f.flush();os.fsync(f.fileno())
        os.replace(name,folder/"update-status.json")
    finally:
        if os.path.exists(name):
            os.unlink(name)


def apply_update(installer: Path, application: Path, expected_version: str,
                 expected_hash: str, parent_pid: int, *, release_lookup=None,
                 wait=None, installer_run=None, relaunch=None,
                 folder: Path | None=None) -> bool:
    """Return success; all side effects restricted to the official installer."""
    folder=Path(folder) if folder is not None else cache_dir()
    folder=folder.resolve(strict=True)
    installer=Path(installer).resolve(strict=True)
    application=Path(application).resolve(strict=True)
    if version_tuple(expected_version)<=version_tuple(APP_VERSION):
        raise UpdateError("Установка старой или текущей версии запрещена")
    if (installer.parent!=folder or
            installer.name!=f"candidate-{expected_version}.exe" or
            application.name.casefold()!="jarvisnova.exe" or
            expected_hash!=expected_hash.lower() or len(expected_hash)!=64):
        raise UpdateError("Недоверенные пути или параметры обновления")
    # Once the owner has closed, ANY verification failure must restore the
    # existing app if it remains intact. Rechecking the API before this try
    # block previously stranded the user with JARVIS closed on network loss.
    (wait or wait_for_parent)(parent_pid)
    try:
        release=(release_lookup or latest_release)()
        if (release is None or release.version!=expected_version
                or release.sha256!=expected_hash
                or release.size<100_000):
            raise UpdateError("Официальный релиз изменился; установка запрещена")
        _check_download(installer,release)
        args=[str(installer),"/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART",
              "/SP-","/CLOSEAPPLICATIONS",f"/DIR={application.parent}"]
        if installer_run is None:
            def installer_run(args):
                flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
                return subprocess.run(args,timeout=MAX_INSTALL_SECONDS,
                                      check=False,creationflags=flags).returncode
        code=installer_run(args)
        if code!=0:
            raise UpdateError(f"Установщик вернул код {code}")
        marker=application.parent/"JARVIS_NOVA_VERSION.txt"
        if not marker.is_file() or marker.read_text("ascii").strip()!=expected_version:
            raise UpdateError("Установленная версия не подтверждена")
        if not application.is_file():
            raise UpdateError("Установщик не создал JarvisNova.exe")
        record_status(folder,"installed",expected_version)
        if relaunch is None:
            def relaunch(exe):
                flags=getattr(subprocess,"DETACHED_PROCESS",0)|getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)
                subprocess.Popen([str(exe)],cwd=str(exe.parent),close_fds=True,
                                 creationflags=flags)
        relaunch(application)
        return True
    except Exception as exc:
        record_status(folder,"failed",expected_version,type(exc).__name__)
        # The old installation may still be functional. Never try to delete it.
        if application.is_file():
            try:
                if relaunch is None:
                    flags=getattr(subprocess,"DETACHED_PROCESS",0)
                    subprocess.Popen([str(application)],cwd=str(application.parent),
                                     close_fds=True,creationflags=flags)
                else:
                    relaunch(application)
            except Exception:
                pass
        raise


def main(argv=None) -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--apply",required=True)
    p.add_argument("--sha256",required=True)
    p.add_argument("--version",required=True)
    p.add_argument("--parent-pid",required=True,type=int)
    p.add_argument("--application",required=True)
    args=p.parse_args(argv)
    try:
        apply_update(Path(args.apply),Path(args.application),
                     args.version,args.sha256,args.parent_pid)
        return 0
    except Exception:
        # Deliberately no untrusted paths, exception details or secrets in logs.
        return 2


if __name__=="__main__":
    sys.exit(main())

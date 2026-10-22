# -*- coding: utf-8 -*-
"""Automatic, verified updates from JARVIS NOVA's OFFICIAL GitHub Releases.

No arbitrary URLs, unsigned scripts, shell commands, force-push branches,
nightly artifacts, releases marked as prerelease/draft, or model downloads.

This is an opt-in *product feature* enabled for actual installed Windows EXEs.
Before any silent installation, GitHub's release-asset SHA256 digest and size
must match the downloaded installer. The updater runs outside the app and
waits for JARVIS to shut down before Inno Setup upgrades the installation.

GitHub Release API integrity is NOT publisher Authenticode code signing.
Future production releases should additionally sign the installer. Until a
qualifying official release is published, this module does nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import urllib.error
import urllib.request

APP_VERSION = "0.5.18"
OWNER = "slucajnyjmarsrut"
REPO = "JARVIS-NOVA"
API_URL = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
MAX_API_BYTES = 700_000
MAX_INSTALLER_BYTES = 4_000_000_000
MIN_INSTALLER_BYTES = 100_000
BUFFER = 1024 * 1024
# GitHub release browser_download_url redirects to its release asset CDN.
ALLOWED_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com",
                            "objects.githubusercontent.com"})
RELEASE_ASSET = re.compile(
    r"^JARVIS-NOVA-(\d+)\.(\d+)\.(\d+)-OFFLINE-SETUP\.exe$", re.I)
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$", re.I)
SHA256 = re.compile(r"^sha256:([a-fA-F0-9]{64})$")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Release:
    version: str
    installer_name: str
    download_url: str
    sha256: str
    size: int


def version_tuple(value: str) -> tuple[int,int,int]:
    if not isinstance(value,str) or not (m:=VERSION.fullmatch(value)):
        raise UpdateError("Неподдерживаемый номер версии")
    return tuple(int(part) for part in m.groups())


def _exact_repo_url(url: str) -> bool:
    try:
        u = urlsplit(url)
        return (u.scheme=="https" and u.hostname=="github.com"
                and u.username is None and u.password is None and u.port is None
                and not u.query and not u.fragment
                and u.path.startswith(f"/{OWNER}/{REPO}/releases/download/"))
    except (ValueError,TypeError):
        return False


def parse_release(data: dict, current: str = APP_VERSION) -> Release | None:
    if not isinstance(data,dict) or data.get("draft") is not False or data.get("prerelease") is not False:
        raise UpdateError("Официального стабильного релиза нет")
    tag=data.get("tag_name")
    ver=version_tuple(tag)
    if ver<=version_tuple(current):
        return None
    if not isinstance(data.get("assets"),list):
        raise UpdateError("Релиз не содержит установщика")
    matches=[]
    for asset in data["assets"]:
        if not isinstance(asset,dict):
            continue
        name=asset.get("name")
        m=RELEASE_ASSET.fullmatch(name) if isinstance(name,str) else None
        if not m or tuple(map(int,m.groups())) != ver:
            continue
        digest=asset.get("digest")
        dm=SHA256.fullmatch(digest) if isinstance(digest,str) else None
        url=asset.get("browser_download_url")
        size=asset.get("size")
        if (not dm or type(size) is not int or not MIN_INSTALLER_BYTES <= size <= MAX_INSTALLER_BYTES
                or not _exact_repo_url(url)
                or urlsplit(url).path != f"/{OWNER}/{REPO}/releases/download/{tag}/{name}"
                or asset.get("state") != "uploaded"):
            raise UpdateError("Установщик не прошёл проверку источника, SHA256 и размера")
        matches.append(Release(".".join(map(str,ver)),name,url,dm.group(1).lower(),size))
    if len(matches)!=1:
        raise UpdateError("Нужен ровно один официальный установщик с SHA256")
    return matches[0]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise UpdateError("Неожиданная переадресация API релизов")


class _RestrictedAssetRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        self.count=0

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        self.count+=1
        if self.count>5 or not _trusted_asset_destination(newurl):
            raise UpdateError("Загрузка перенаправлена на недоверенный адрес")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _trusted_asset_destination(url: str) -> bool:
    try:
        u=urlsplit(url)
        return (u.scheme=="https" and u.hostname in ALLOWED_HOSTS
                and u.username is None and u.password is None and u.port is None
                and not u.fragment)
    except (ValueError,TypeError):
        return False


def latest_release(*, requester=None, current=APP_VERSION) -> Release | None:
    """Fixed upstream only. A downloader's arbitrary URL is never accepted."""
    if requester is None:
        def requester():
            opener=urllib.request.build_opener(
                urllib.request.ProxyHandler({}),_NoRedirect())
            req=urllib.request.Request(API_URL,headers={
                "Accept":"application/vnd.github+json",
                "User-Agent":"JARVIS-NOVA-Verified-Updater/1",
                "X-GitHub-Api-Version":"2022-11-28"})
            with opener.open(req,timeout=12) as response:
                return response.read(MAX_API_BYTES+1)
    try:
        raw=requester()
    except urllib.error.HTTPError as exc:
        if exc.code==404:
            return None  # no official published release yet
        raise UpdateError("Сервис релизов недоступен") from exc
    if not isinstance(raw,bytes) or len(raw)>MAX_API_BYTES:
        raise UpdateError("Недопустимый ответ сервера обновлений")
    try:
        data=json.loads(raw.decode("utf-8"))
    except (ValueError,UnicodeError) as exc:
        raise UpdateError("Некорректное описание обновления") from exc
    return parse_release(data,current)


def cache_dir() -> Path:
    base=os.environ.get("LOCALAPPDATA")
    if not base:
        raise UpdateError("Отсутствует LOCALAPPDATA, автообновление отключено")
    return Path(base)/"JarvisNova"/"Updates"


def _prepare_cache(folder: Path) -> None:
    # Never follow a symlink at any level controlled by the application.
    folder=Path(folder)
    if folder.is_symlink() or folder.parent.is_symlink():
        raise UpdateError("Недоверенный каталог обновлений")
    folder.mkdir(parents=True,exist_ok=True)
    if not folder.is_dir() or folder.is_symlink():
        raise UpdateError("Невозможно создать безопасный каталог обновлений")


def hash_file(path: Path) -> tuple[int,str]:
    h=hashlib.sha256()
    length=0
    with Path(path).open("rb") as f:
        while chunk:=f.read(BUFFER):
            length+=len(chunk)
            if length>MAX_INSTALLER_BYTES:
                raise UpdateError("Превышен предел размера установщика")
            h.update(chunk)
    return length,h.hexdigest()


def _check_download(path: Path, release: Release) -> None:
    if path.is_symlink() or not path.is_file():
        raise UpdateError("Недоверенный файл обновления")
    length,digest=hash_file(path)
    if length!=release.size or digest!=release.sha256:
        raise UpdateError("SHA256 или размер установщика не совпадают")
    with path.open("rb") as f:
        if f.read(2)!=b"MZ":
            raise UpdateError("Загружен не Windows EXE")


def download_release(release: Release, folder: Path, *,
                     opener=None, cancel: threading.Event | None=None) -> Path:
    """Download one verified installer. Never execute bytes from an API field."""
    if not isinstance(release,Release) or not _exact_repo_url(release.download_url):
        raise UpdateError("Недоверенный адрес")
    version_tuple(release.version)
    if (release.installer_name != f"JARVIS-NOVA-{release.version}-OFFLINE-SETUP.exe"
            or urlsplit(release.download_url).path.split("/")[-1] != release.installer_name):
        raise UpdateError("Адрес и имя файла не совпадают с подтверждённым релизом")
    if (not SHA256.fullmatch("sha256:"+release.sha256)
            or type(release.size) is not int
            or not MIN_INSTALLER_BYTES<=release.size<=MAX_INSTALLER_BYTES):
        raise UpdateError("Отсутствуют контрольные данные")
    if cancel is not None and cancel.is_set():
        raise UpdateError("Загрузка отменена")
    folder=Path(folder)
    _prepare_cache(folder)
    dest=folder/f"candidate-{release.version}.exe"
    if dest.exists() or dest.is_symlink():
        _check_download(dest,release)
        return dest
    temp=folder/f".candidate-{release.version}-{secrets.token_hex(6)}.part"
    try:
        if opener is None:
            opener=urllib.request.build_opener(
                urllib.request.ProxyHandler({}),_RestrictedAssetRedirect())
        req=urllib.request.Request(release.download_url,headers={
            "User-Agent":"JARVIS-NOVA-Verified-Updater/1"})
        response=opener.open(req,timeout=90)
        with response, temp.open("xb") as writer:
            count=0
            digest=hashlib.sha256()
            while True:
                if cancel is not None and cancel.is_set():
                    raise UpdateError("Загрузка отменена")
                piece=response.read(BUFFER)
                if not piece:
                    break
                count+=len(piece)
                if count>release.size:
                    raise UpdateError("Сервер вернул слишком большой файл")
                writer.write(piece)
                digest.update(piece)
        if count!=release.size or digest.hexdigest()!=release.sha256:
            raise UpdateError("Неполная загрузка или неверный SHA256")
        with temp.open("rb") as f:
            if f.read(2)!=b"MZ":
                raise UpdateError("Это не EXE")
        if dest.exists() or dest.is_symlink():
            _check_download(dest,release)
        else:
            os.replace(temp,dest)
        return dest
    finally:
        temp.unlink(missing_ok=True)


def installed_application(executable: str | None=None, *, frozen: bool | None=None) -> Path | None:
    exe=Path(executable or sys.executable)
    if (getattr(sys,"frozen",False) if frozen is None else frozen) is not True:
        return None
    if os.name!="nt" and frozen is None:
        return None
    if exe.name.casefold()!="jarvisnova.exe" or not exe.is_file():
        return None
    if not (exe.parent/"JarvisNovaUpdater.exe").is_file():
        return None
    return exe


def stage_helper(release: Release, installer: Path, application: Path,
                 folder: Path, *, launcher=subprocess.Popen) -> None:
    """Detach a LOCAL packaged helper; caller then closes JARVIS gracefully."""
    if not isinstance(release,Release):
        raise UpdateError("Некорректная версия")
    _check_download(Path(installer),release)
    application=Path(application).resolve(strict=True)
    if application.name.casefold()!="jarvisnova.exe":
        raise UpdateError("Обновлять разрешено только JARVIS NOVA")
    helper=application.parent/"JarvisNovaUpdater.exe"
    if not helper.is_file():
        raise UpdateError("Отдельный процесс обновления не установлен")
    folder=Path(folder)
    _prepare_cache(folder)
    # The helper must run outside Inno Setup's installation directory.
    detached=folder/("JARVIS-NOVA-Worker-"+secrets.token_hex(6)+".exe")
    # Create exclusively and don't replace a possibly-running Windows worker.
    with helper.open("rb") as source, detached.open("xb") as target:
        shutil.copyfileobj(source,target,length=BUFFER)
    try:
        flags=getattr(subprocess,"CREATE_NO_WINDOW",0)
        launcher([str(detached),"--apply",str(installer),"--sha256",release.sha256,
                  "--version",release.version,"--parent-pid",str(os.getpid()),
                  "--application",str(application)],
                 cwd=str(folder),close_fds=True,creationflags=flags)
    except Exception:
        detached.unlink(missing_ok=True)
        raise


def check_and_download(*, requester=None, opener=None,
                       cancel=None, folder=None) -> tuple[Release,Path] | None:
    release=latest_release(requester=requester)
    if release is None:
        return None
    file=download_release(release,folder or cache_dir(),opener=opener,cancel=cancel)
    return release,file

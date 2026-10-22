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
import time
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
GITHUB_ASSET_LIMIT = 2 * 1024**3  # release assets must be STRICTLY smaller
MAX_PARTS = 8
RETRY_FAILED_AFTER = 24 * 60 * 60
DISK_RESERVE_BYTES = 700_000_000
BUFFER = 1024 * 1024
# GitHub release browser_download_url redirects to its release asset CDN.
ALLOWED_HOSTS = frozenset({"github.com", "release-assets.githubusercontent.com",
                            "objects.githubusercontent.com"})
RELEASE_ASSET = re.compile(
    r"^JARVIS-NOVA-(\d+)\.(\d+)\.(\d+)-OFFLINE-SETUP\.exe$", re.I)
RELEASE_PART = re.compile(
    r"^JARVIS-NOVA-(\d+)\.(\d+)\.(\d+)-OFFLINE-SETUP\.exe\.part(\d{2})$", re.I)
VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$", re.I)
SHA256 = re.compile(r"^sha256:([a-fA-F0-9]{64})$")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleasePart:
    name: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class Release:
    version: str
    installer_name: str
    download_url: str
    sha256: str
    size: int
    parts: tuple[ReleasePart, ...] = ()


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


def _official_asset(asset: dict, tag: str, *, expected_name: str,
                    min_size: int=1, max_size: int=GITHUB_ASSET_LIMIT-1) -> ReleasePart:
    name=asset.get("name")
    digest=asset.get("digest")
    dm=SHA256.fullmatch(digest) if isinstance(digest,str) else None
    url=asset.get("browser_download_url")
    size=asset.get("size")
    if (name!=expected_name or not dm or type(size) is not int
            or not min_size<=size<=max_size or not _exact_repo_url(url)
            or urlsplit(url).path!=f"/{OWNER}/{REPO}/releases/download/{tag}/{name}"
            or asset.get("state")!="uploaded"):
        raise UpdateError("Часть обновления не прошла проверку имени, адреса, SHA256 или размера")
    return ReleasePart(name,url,dm.group(1).lower(),size)


def _manifest_fields(body: str) -> tuple[str,int]:
    """A release-author supplied combined hash, plus per-asset GitHub digests."""
    if not isinstance(body,str) or len(body)>30_000:
        raise UpdateError("Отсутствует компактный манифест установщика")
    hashes=re.findall(r"(?m)^JARVIS-NOVA-INSTALLER-SHA256: ([a-f0-9]{64})\s*$",body)
    sizes=re.findall(r"(?m)^JARVIS-NOVA-INSTALLER-SIZE: (\d{6,12})\s*$",body)
    if len(hashes)!=1 or len(sizes)!=1:
        raise UpdateError("Манифест многотомного установщика отсутствует или неоднозначен")
    size=int(sizes[0])
    if not MIN_INSTALLER_BYTES<=size<=MAX_INSTALLER_BYTES:
        raise UpdateError("Общий размер установщика недопустим")
    return hashes[0],size


def parse_release(data: dict, current: str = APP_VERSION) -> Release | None:
    if not isinstance(data,dict) or data.get("draft") is not False or data.get("prerelease") is not False:
        raise UpdateError("Официального стабильного релиза нет")
    tag=data.get("tag_name")
    ver=version_tuple(tag)
    if ver<=version_tuple(current):
        return None
    if not isinstance(data.get("assets"),list):
        raise UpdateError("Релиз не содержит установщика")
    version=".".join(map(str,ver))
    base=f"JARVIS-NOVA-{version}-OFFLINE-SETUP.exe"
    singles=[]
    found_parts={}
    for asset in data["assets"]:
        if not isinstance(asset,dict):
            continue
        name=asset.get("name")
        if name==base:
            part=_official_asset(asset,tag,expected_name=base,
                min_size=MIN_INSTALLER_BYTES)
            singles.append(part)
        elif isinstance(name,str) and name.startswith(base+".part"):
            match=RELEASE_PART.fullmatch(name)
            if not match or tuple(map(int,match.groups()[:3]))!=ver:
                raise UpdateError("Неправильное имя части установщика")
            index=int(match.group(4))
            if index<1 or index>MAX_PARTS or index in found_parts:
                raise UpdateError("Дублирующаяся или лишняя часть установщика")
            found_parts[index]=_official_asset(asset,tag,expected_name=name)
    if len(singles)==1 and not found_parts:
        item=singles[0]
        return Release(version,base,item.url,item.sha256,item.size)
    if singles or not (2<=len(found_parts)<=MAX_PARTS):
        raise UpdateError("Для обновления нужен один EXE или проверенный комплект частей")
    if set(found_parts)!=set(range(1,len(found_parts)+1)):
        raise UpdateError("В многотомном установщике отсутствует часть")
    full_hash,full_size=_manifest_fields(data.get("body"))
    parts=tuple(found_parts[i] for i in range(1,len(found_parts)+1))
    if sum(part.size for part in parts)!=full_size:
        raise UpdateError("Общий размер частей не соответствует манифесту")
    return Release(version,base,parts[0].url,full_hash,full_size,parts)


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
    if release.installer_name != f"JARVIS-NOVA-{release.version}-OFFLINE-SETUP.exe":
        raise UpdateError("Некорректное имя установщика")
    parts=release.parts or (ReleasePart(release.installer_name,release.download_url,
                                        release.sha256,release.size),)
    if (release.parts and (not 2<=len(parts)<=MAX_PARTS or
            release.download_url!=parts[0].url or
            sum(p.size for p in parts)!=release.size)):
        raise UpdateError("Некорректный комплект частей установщика")
    for index,p in enumerate(parts,1):
        expected=(release.installer_name+f".part{index:02d}"
                  if release.parts else release.installer_name)
        if (p.name!=expected or not _exact_repo_url(p.url)
                or urlsplit(p.url).path.split("/")[-1]!=expected
                or not SHA256.fullmatch("sha256:"+p.sha256)
                or type(p.size) is not int or not 1<=p.size<GITHUB_ASSET_LIMIT):
            raise UpdateError("Части релиза или контрольные суммы не подтверждены")
    if (not SHA256.fullmatch("sha256:"+release.sha256)
            or type(release.size) is not int
            or not MIN_INSTALLER_BYTES<=release.size<=MAX_INSTALLER_BYTES):
        raise UpdateError("Отсутствуют контрольные данные")
    if cancel is not None and cancel.is_set():
        raise UpdateError("Загрузка отменена")
    folder=Path(folder)
    _prepare_cache(folder)
    dest=folder/f"candidate-{release.version}.exe"
    # A damaged cached installer is NOT executed. Download a fresh verified
    # copy and atomically replace only the updater-owned candidate pathname.
    if dest.is_symlink():
        raise UpdateError("В каталоге обновлений обнаружена ссылка вместо EXE")
    if dest.exists():
        try:
            _check_download(dest,release)
            return dest
        except UpdateError:
            pass
    if shutil.disk_usage(folder).free < release.size + DISK_RESERVE_BYTES:
        raise UpdateError("Недостаточно свободного места для безопасного обновления")
    temp=folder/f".candidate-{release.version}-{secrets.token_hex(6)}.part"
    try:
        if opener is None:
            opener=urllib.request.build_opener(
                urllib.request.ProxyHandler({}),_RestrictedAssetRedirect())
        count=0
        digest=hashlib.sha256()
        with temp.open("xb") as writer:
            for part in parts:
                req=urllib.request.Request(part.url,headers={
                    "User-Agent":"JARVIS-NOVA-Verified-Updater/1"})
                response=opener.open(req,timeout=90)
                part_count=0
                part_digest=hashlib.sha256()
                with response:
                    while True:
                        if cancel is not None and cancel.is_set():
                            raise UpdateError("Загрузка отменена")
                        piece=response.read(BUFFER)
                        if not piece:
                            break
                        part_count+=len(piece)
                        count+=len(piece)
                        if part_count>part.size or count>release.size:
                            raise UpdateError("Сервер вернул слишком большой файл")
                        writer.write(piece)
                        part_digest.update(piece)
                        digest.update(piece)
                if part_count!=part.size or part_digest.hexdigest()!=part.sha256:
                    raise UpdateError("Контрольная сумма части обновления не совпала")
        if count!=release.size or digest.hexdigest()!=release.sha256:
            raise UpdateError("Неполная загрузка или неверный SHA256")
        with temp.open("rb") as f:
            if f.read(2)!=b"MZ":
                raise UpdateError("Это не EXE")
        if dest.is_symlink():
            raise UpdateError("Недоверенный файл появился во время загрузки")
        # Replacing a previously corrupted cache is safe only AFTER a complete
        # independent SHA256 and content verification of the fresh download.
        os.replace(temp,dest)
        _check_download(dest,release)
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


def _recent_failed_version(folder: Path, version: str, now: float | None=None) -> bool:
    """Avoid an endless install-fail-restart loop for a broken stable release."""
    path=Path(folder)/"update-status.json"
    try:
        if path.is_symlink() or path.stat().st_size>4096:
            return False
        data=json.loads(path.read_text("utf-8"))
        instant=float(data.get("checked_at",0))
        instant=time.time() if now is None else now
        age=instant-float(data.get("checked_at",0))
        return (data.get("status")=="failed" and data.get("version")==version
                and 0<=age<RETRY_FAILED_AFTER)
    except (OSError,TypeError,ValueError,UnicodeError,AttributeError):
        return False


def check_and_download(*, requester=None, opener=None,
                       cancel=None, folder=None) -> tuple[Release,Path] | None:
    release=latest_release(requester=requester)
    if release is None:
        return None
    folder=Path(folder) if folder is not None else cache_dir()
    if _recent_failed_version(folder,release.version):
        return None
    file=download_release(release,folder,opener=opener,cancel=cancel)
    return release,file

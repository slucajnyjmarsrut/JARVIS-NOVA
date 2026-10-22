# -*- coding: utf-8 -*-
"""Conservative local self-repair for JARVIS NOVA.

Real autonomous repairs, with strict bounds:
* Known transient READ-ONLY operations get one safe retry.
* Corrupted learning/mode settings can be backed up and recreated only after
  the user's explicit confirmation, with neither scripts nor shell commands.
* Source code, models, installer, footage, logs and private media are NEVER
  rewritten, downloaded or uploaded.
"""
from __future__ import annotations

from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
from typing import Callable, TypeVar
import urllib.error

from self_improve import default_data_file, safe_name, MAX_ALIASES

T = TypeVar("T")
MAX_BACKUPS = 30
MAX_REPAIR_BYTES = 512_000  # never copy huge user-owned files automatically
READ_ONLY_OPERATIONS = frozenset({
    "commons_search", "official_ffmpeg_docs", "ffprobe_read", "model_health_probe",
})
_RETRY_ERRNOS = frozenset({
    errno.ECONNRESET, errno.ECONNABORTED, errno.ETIMEDOUT,
    errno.EPIPE, errno.EHOSTUNREACH, errno.ENETUNREACH,
})

# Exact filenames and version; never accept names or commands from a model.
CONFIG = {
    "learning-v1.json": (40_000, frozenset({"aliases", "stats"})),
    "modes-v1.json": (8_192, frozenset({"apps"})),
}


class RepairError(RuntimeError):
    pass


@dataclass(frozen=True)
class Finding:
    name: str
    status: str  # healthy, absent, corrupt, too_large, unsupported, unsafe
    description: str


@dataclass(frozen=True)
class RepairReport:
    found: tuple[Finding, ...]
    repaired: tuple[str, ...]
    backed_up: tuple[str, ...]
    manual: tuple[str, ...]

    def say(self) -> str:
        damaged=sum(x.status in {"corrupt","too_large"} for x in self.found)
        repaired=len(self.repaired)
        if repaired:
            ending=(" Некоторые настройки требуют ручной проверки и не изменены."
                    if self.manual else "")
            return (f"Проверил конфигурацию. Безопасно восстановил {repaired} "
                    "файлов. Оригиналы сохранены в резервных копиях."+ending)
        if damaged:
            return "Обнаружены повреждённые настройки. Автоматический ремонт не завершён; оригиналы сохранены."
        if self.manual:
            return "Некоторые настройки требуют ручной проверки. Я не изменял их."
        return "Проверил настройки. Известных повреждений не обнаружено."


def _classify(path: Path, name: str) -> Finding:
    limit, fields=CONFIG[name]
    if path.is_symlink():
        return Finding(name,"unsafe","Ссылка вместо файла: не трогаю")
    if not path.exists():
        return Finding(name,"absent","Настройки ещё не созданы")
    if not path.is_file():
        return Finding(name,"unsafe","Это не обычный файл: не трогаю")
    try:
        size=path.stat().st_size
        if size > MAX_REPAIR_BYTES:
            return Finding(name,"unsafe","Слишком большой файл: только ручная проверка")
        if size > limit:
            return Finding(name,"too_large","Файл превышает безопасный предел")
        payload=path.read_bytes()
        doc=json.loads(payload.decode("utf-8"))
    except (OSError,ValueError,UnicodeError,TypeError):
        return Finding(name,"corrupt","Повреждён JSON настроек")
    if not isinstance(doc,dict):
        return Finding(name,"corrupt","Настройки имеют неверный формат")
    if doc.get("version") != 1:
        return Finding(name,"unsupported","Другая версия настроек: не переписываю")
    for field in fields:
        if field in doc and not isinstance(doc[field],dict):
            return Finding(name,"corrupt","Повреждена структура настроек")
    if name=="learning-v1.json":
        aliases=doc.get("aliases",{})
        # A syntactically valid JSON object can still carry shell names that
        # LearningStore would silently reject. Such personal data is never
        # automatically reset; the owner must inspect or explicitly remove it.
        if len(aliases)>MAX_ALIASES or any(
                not safe_name(key) or not safe_name(value)
                for key,value in aliases.items()):
            return Finding(name,"unsafe","Небезопасные названия программ: ручная проверка")
    elif name=="modes-v1.json":
        from work_modes import MODES
        apps=doc.get("apps",{})
        if any(mode not in MODES for mode in apps):
            return Finding(name,"unsupported","Неизвестный режим: не перезаписываю")
        if any(type(items) is not list or not 1<=len(items)<=3 or
               any(not safe_name(app) for app in items)
               for items in apps.values()):
            return Finding(name,"unsafe","Некорректный список приложений: ручная проверка")
    return Finding(name,"healthy","Формат и разрешённые значения настроек корректны")


def inspect_configs(folder: Path | None = None) -> tuple[Finding, ...]:
    """Read-only local inspection; never scans arbitrary folders recursively."""
    folder=Path(folder) if folder is not None else default_data_file().parent
    if folder.is_symlink():
        return tuple(Finding(name,"unsafe","Каталог настроек является ссылкой")
                     for name in CONFIG)
    return tuple(_classify(folder/name,name) for name in CONFIG)


def _backup_exclusive(source: Path) -> Path:
    for number in range(1,MAX_BACKUPS+1):
        backup=source.with_name(source.name+f".corrupt-{number}.bak")
        try:
            with backup.open("xb") as stream:
                try:
                    with source.open("rb") as original:
                        size=os.fstat(original.fileno()).st_size
                        if size>MAX_REPAIR_BYTES:
                            raise RepairError("Настройки изменились: файл слишком велик")
                        # Bounded copy even if another process grows the
                        # settings file during backup; never fill the disk.
                        data=original.read(MAX_REPAIR_BYTES+1)
                        if len(data)>MAX_REPAIR_BYTES or len(data)!=size:
                            raise RepairError("Настройки изменились при копировании")
                        stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                except Exception:
                    stream.close()
                    backup.unlink(missing_ok=True)
                    raise
            return backup
        except FileExistsError:
            continue
    raise RepairError("Лимит резервных копий достигнут")


def _backup_still_matches(source: Path, backup: Path) -> bool:
    """Fail closed if another process repaired/changed the live config."""
    try:
        if source.is_symlink() or not source.is_file():
            return False
        if source.stat().st_size>MAX_REPAIR_BYTES:
            return False
        with source.open("rb") as current, backup.open("rb") as saved:
            live=current.read(MAX_REPAIR_BYTES+1)
            copy=saved.read(MAX_REPAIR_BYTES+1)
        return len(live)<=MAX_REPAIR_BYTES and live==copy
    except OSError:
        return False


def _reset_atomic(target: Path) -> None:
    fd,temp=tempfile.mkstemp(prefix=".jarvis-repair-",suffix=".tmp",
                            dir=str(target.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            fields={field:{} for field in CONFIG[target.name][1]}
            json.dump({"version":1,**fields},out,ensure_ascii=False)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp,target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def repair_configs(*, consent: bool = False, folder: Path | None = None) -> RepairReport:
    """Opt-in repair known broken settings, keeping an exclusive full backup.

    This intentionally does NOT fix code bugs or move/delete models.
    Unknown future-version settings and symlinks are left intact.
    """
    if not consent:
        raise PermissionError("Для восстановления настроек необходимо подтверждение")
    folder=Path(folder) if folder is not None else default_data_file().parent
    found=inspect_configs(folder)
    repaired=[]
    backups=[]
    manual=[]
    if folder.is_symlink():
        return RepairReport(found,(),(),("Небезопасный каталог настроек",))
    for entry in found:
        if entry.status not in ("corrupt","too_large"):
            if entry.status in ("unsafe","unsupported"):
                manual.append(entry.name)
            continue
        target=folder/entry.name
        # Recheck immediately before touching user data.
        latest=_classify(target,entry.name)
        if latest.status not in ("corrupt","too_large"):
            manual.append(entry.name)
            continue
        try:
            backup=_backup_exclusive(target)
            backups.append(backup.name)
            # Recheck after backup: another instance may have replaced its
            # corrupt settings with a valid profile during this very copy.
            if not _backup_still_matches(target,backup):
                manual.append(entry.name)
                continue
            _reset_atomic(target)
            if _classify(target,entry.name).status!="healthy":
                raise RepairError("Повторная проверка исправленного файла не прошла")
            repaired.append(entry.name)
        except (OSError,RepairError):
            manual.append(entry.name)
            # Never delete a backup even on partial failure.
    return RepairReport(found,tuple(repaired),tuple(backups),tuple(manual))


def retry_readonly(operation: str, action: Callable[[], T], *,
                   cancel: threading.Event | None = None) -> T:
    """At most two executions of explicitly allowed read-only operations.

    Never retries file writes, media downloads, installs, uploads, clicks,
    code patches or AI-generated commands. An operation's original consent
    and permissions must already have been checked by its caller.
    """
    if operation not in READ_ONLY_OPERATIONS:
        raise PermissionError("Автоповтор этой операции не разрешён")
    if cancel is not None and cancel.is_set():
        raise RepairError("Операция отменена")
    for attempt in range(2):
        try:
            return action()
        except (TimeoutError,ConnectionError,OSError,urllib.error.URLError) as exc:
            if cancel is not None and cancel.is_set():
                raise RepairError("Операция отменена") from exc
            # A real HTTP 4xx/5xx response is not a connection interruption.
            # Do not repeat forbidden/invalid requests or rate-limit errors.
            is_transient=(not isinstance(exc,urllib.error.HTTPError) and
                (isinstance(exc,(TimeoutError,ConnectionError,
                                 urllib.error.URLError)) or
                 (type(exc) is OSError and exc.errno in _RETRY_ERRNOS)))
            if not is_transient or attempt==1:
                raise
    raise AssertionError("unreachable")

# -*- coding: utf-8 -*-
"""Conservative local self-improvement: learn confirmed application aliases.

Never downloads, rewrites or executes code. No raw speech, screenshots, typed
text, credentials or file paths are persisted. Aliases can be removed or reset.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
from pathlib import Path
import json
import os
import re
import tempfile
import threading

# Do not permit a learned alias to launch a scripting or privileged tool.
BLOCKED = frozenset({
    "powershell", "powershell.exe", "pwsh", "cmd", "cmd.exe", "regedit",
    "regedit.exe", "terminal", "windows terminal", "wscript", "cscript",
    "taskkill", "taskmgr", "mshta", "rundll32", "reg", "shutdown",
    "control panel", "панель управления", "диспетчер задач",
    "windows powershell", "powershell 7", "командная строка",
    "редактор реестра", "command prompt", "git bash",
    "отмена", "стоп", "прекрати", "джарвис", "жарвис",
})
# Keep aliases short and data-only: never scripts, URLs, switches or filesystem paths.
SAFE_NAME = re.compile(r"^[\wа-яё][\wа-яё ._-]{1,63}$", re.IGNORECASE)
MAX_ALIASES = 120
MAX_COUNT = 1_000_000


def canonicalize(value: str) -> str:
    return " ".join(value.lower().replace("ё", "е").strip().split())


def safe_name(value: str) -> bool:
    if not isinstance(value, str):
        return False
    cleaned = canonicalize(value)
    if len(cleaned) < 2 or len(cleaned) > 64 or not SAFE_NAME.fullmatch(cleaned):
        return False
    if cleaned in BLOCKED or cleaned.startswith(("http", "file", "www")):
        return False
    if ".." in cleaned or "\\" in cleaned or "/" in cleaned or ":" in cleaned:
        return False
    return True


def default_data_file() -> Path:
    # No writes under PyInstaller _MEIPASS; user data persists across updates.
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "JarvisNova" / "learning-v1.json"
    return Path.home() / ".jarvisnova" / "learning-v1.json"


class LearningStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else default_data_file()
        self.lock = threading.RLock()
        self.aliases: dict[str, str] = {}
        self.stats: dict[str, dict[str, int]] = {}
        self._loaded_digest: str | None = None
        self._read_only = False
        self._load()

    def _load(self):
        if self.path.is_symlink():
            self._read_only=True
            return
        if not self.path.exists():
            return
        try:
            if not self.path.is_file() or not 0 < self.path.stat().st_size <= 40_000:
                self._read_only=True
                return
            payload=self.path.read_bytes()
            if len(payload)>40_000:
                self._read_only=True
                return
            doc=json.loads(payload.decode("utf-8"))
            if not isinstance(doc,dict) or type(doc.get("version")) is not int or doc["version"]!=1:
                self._read_only=True
                return
            aliases=doc.get("aliases",{})
            stats=doc.get("stats",{})
            if not isinstance(aliases,dict) or not isinstance(stats,dict):
                self._read_only=True
                return
            self._loaded_digest=hashlib.sha256(payload).hexdigest()
            if len(aliases)>MAX_ALIASES:
                self._read_only=True
            for key,value in list(aliases.items())[:MAX_ALIASES]:
                if safe_name(key) and safe_name(value):
                    self.aliases[canonicalize(key)]=value.strip()
                else:
                    self._read_only=True
            for key,values in stats.items():
                if not isinstance(key,str) or not re.fullmatch(r"[a-z_]{2,24}",key):
                    self._read_only=True
                    continue
                if not isinstance(values,dict):
                    self._read_only=True
                    continue
                self.stats[key]={}
                for label in ("ok","fail"):
                    n=values.get(label,0)
                    if type(n) is not int or not 0<=n<=MAX_COUNT:
                        self._read_only=True
                    self.stats[key][label]=max(0,min(n,MAX_COUNT)) if type(n) is int else 0
        except (ValueError,UnicodeError,OSError,TypeError):
            # Starting safely is fine, but silently writing an empty replacement
            # after startup would destroy the owner's damaged learning file.
            self._read_only=True
            return

    def _check_unchanged(self):
        if self._read_only or self.path.is_symlink():
            raise RuntimeError("Настройки обучения повреждены или небезопасны; нужна ручная проверка")
        if self.path.exists():
            if self._loaded_digest is None or not self.path.is_file():
                raise RuntimeError("Файл обучения изменён другим процессом")
            if self.path.stat().st_size>40_000:
                raise RuntimeError("Файл обучения превышает безопасный предел")
            data=self.path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=self._loaded_digest:
                raise RuntimeError("Файл обучения изменён другим процессом")
        elif self._loaded_digest is not None:
            raise RuntimeError("Файл обучения был удалён другим процессом")

    def _save(self):
        self._check_unchanged()
        doc={"version":1,"aliases":self.aliases,"stats":self.stats}
        payload=json.dumps(doc,ensure_ascii=False,indent=2,sort_keys=True)
        digest=hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        fd,filename=tempfile.mkstemp(prefix=".jarvis-learning-",suffix=".tmp",
                                      dir=str(self.path.parent))
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            # Recheck AFTER the temp write too; do not replace a file another
            # JARVIS instance updated while the temp file was being written.
            self._check_unchanged()
            os.replace(filename,self.path)
            self._loaded_digest=digest
        finally:
            if os.path.exists(filename):
                os.unlink(filename)

    def resolve(self, spoken: str) -> str | None:
        with self.lock:
            return self.aliases.get(canonicalize(spoken))

    def learn(self, spoken: str, official: str, verified: bool = False):
        """Called only after user confirmation AND installed shortcut verification."""
        if not verified:
            raise PermissionError("Нужно подтвердить существование установленной программы")
        if not safe_name(spoken) or not safe_name(official):
            raise ValueError("Недопустимое название программы")
        with self.lock:
            k = canonicalize(spoken)
            if k not in self.aliases and len(self.aliases) >= MAX_ALIASES:
                raise ValueError("Слишком много выученных названий")
            self.aliases[k] = official.strip()
            self._save()

    def unlearn(self, spoken: str):
        with self.lock:
            if self.aliases.pop(canonicalize(spoken), None) is not None:
                self._save()
                return True
            return False

    def feedback(self, action_kind: str, success: bool):
        # Aggregate only action types, never texts/screenshots/URLs or arguments.
        if not re.fullmatch(r"[a-z_]{2,24}", action_kind):
            return
        with self.lock:
            score = self.stats.setdefault(action_kind, {"ok": 0, "fail": 0})
            key = "ok" if success else "fail"
            score[key] = min(MAX_COUNT, score.get(key, 0) + 1)
            self._save()

    def summary(self) -> str:
        with self.lock:
            entries = sorted(self.stats.items(), key=lambda item: -item[1].get("fail", 0))
            lines = [f"Выучено названий программ: {len(self.aliases)}"]
            for label, values in entries[:10]:
                lines.append(f"{label}: успешно {values.get('ok', 0)}, ошибки {values.get('fail', 0)}")
            lines.append("Изменения применяются только к названиям программ после подтверждения.")
            lines.append("Команды, голосовые записи и снимки экрана не сохраняются.")
            return "\n".join(lines)

    def reset(self):
        with self.lock:
            self.aliases.clear()
            self.stats.clear()
            self._save()


def propose_installed_name(query: str, installed: list[str]) -> str | None:
    """Suggest a similar *installed* shortcut; never auto-launch a fuzzy match."""
    if not safe_name(query) or len(canonicalize(query)) < 4:
        return None
    entries: list[tuple[float, str]] = []
    cleaned_query = canonicalize(query)
    for name in set(installed):
        if not safe_name(name):
            continue
        key = canonicalize(name)
        if key == cleaned_query:
            return None  # exact lookup belongs to normal app discovery
        ratio = SequenceMatcher(None, cleaned_query, key).ratio()
        entries.append((ratio, name))
    if not entries:
        return None
    entries.sort(key=lambda item: (-item[0], item[1]))
    if entries[0][0] < 0.73:
        return None
    if len(entries) > 1 and entries[0][0] - entries[1][0] < 0.06:
        return None
    return entries[0][1]

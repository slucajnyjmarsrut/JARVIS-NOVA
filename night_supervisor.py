# -*- coding: utf-8 -*-
"""JARVIS NOVA overnight supervisor: durable, bounded, local and fail-closed.

The supervisor is deterministic code, NOT a model with Windows privileges.
Only three allowlisted tasks are available: new Python source projects,
Gemma3 screenplays, and Llama montage *advice* for a finished screenplay.
No deletion, arbitrary scripts, browser, publishing, downloads or OS control.
An upfront, task-specific approval grants local model inference and creation
of NEW output files under the supervisor's own directory only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from hashlib import sha256
from tempfile import TemporaryDirectory
import json
import os
import sqlite3
import stat
import threading
import time
from uuid import uuid4

KINDS = ("scenario", "code", "montage_advice")
MAX_JOBS = 12
MAX_DATA_BYTES = 750_000
MAX_PROMPT_CHARS = 2400
REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class SupervisorError(RuntimeError):
    """A task was blocked, not silently executed or misreported as complete."""


@dataclass(frozen=True)
class NightJob:
    id: str
    kind: str
    prompt: str
    status: str
    step: str
    language: str
    source_id: str
    output: str
    error: str


def _time():
    return datetime.now(timezone.utc).isoformat()


def _no_links(path: Path):
    """Reject any existing symlink or Windows junction in a writable path."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (
                os.name == "nt" and
                bool(getattr(info, "st_file_attributes", 0) & REPARSE)):
            raise SupervisorError("Символические ссылки и junction запрещены.")


def _brief_from_data(data):
    from viral_studio import Brief, Shot, Trend, validate_brief
    if not isinstance(data, dict) or len(data) > 12:
        raise SupervisorError("Некорректная структура сценария.")
    try:
        shots = tuple(Shot(**shot) for shot in data["shots"])
        trends = tuple(Trend(**item) for item in data.get("research", ()))
        brief = Brief(data["title"], data["topic"], data["hook"],
                      data["script"], shots, data["call_to_action"],
                      data["generator"], trends)
        return validate_brief(brief)
    except (KeyError, TypeError, ValueError) as exc:
        raise SupervisorError("Некорректный сценарий в контрольной точке.") from exc


def _plan_from_data(data):
    from code_workspace import ChangePlan, ProposedFile, validate_plan
    if not isinstance(data, dict) or data.get("language") != "python":
        raise SupervisorError("Ночная проверка кода поддерживает только Python.")
    try:
        files = tuple(ProposedFile(p["path"], p["content"])
                      for p in data["files"])
        return validate_plan(ChangePlan("python", files))
    except (KeyError, TypeError, ValueError) as exc:
        raise SupervisorError("Контрольная точка кода повреждена.") from exc


class NightSupervisor:
    """Serial checkpointed queue with SQLite transactions and an audit journal.

    Executor injection is for offline tests only; independent validators
    are always invoked after it. The actual UI never injects executors.
    """
    def __init__(self, root=None, *, executor=None):
        self.root = Path(root if root is not None else
                         Path.home() / "JARVIS-NOVA-Projects" /
                         "Night-Supervisor").absolute()
        _no_links(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "night_jobs.sqlite3"
        _no_links(self.db)
        self._run_lock = threading.Lock()
        self._executor = executor or self._generate
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, prompt TEXT NOT NULL,
                language TEXT NOT NULL, source_id TEXT NOT NULL,
                status TEXT NOT NULL, step TEXT NOT NULL,
                output TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                created TEXT NOT NULL, approved INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                job_id TEXT NOT NULL, step TEXT NOT NULL, payload TEXT NOT NULL,
                digest TEXT NOT NULL, PRIMARY KEY(job_id,step))""")
            db.execute("""CREATE TABLE IF NOT EXISTS journal (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                created TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL)""")
            # No automatic replay of interrupted work; user authorizes resume.
            ids = [row[0] for row in db.execute(
                "SELECT id FROM jobs WHERE status='running'")]
            for job_id in ids:
                db.execute("UPDATE jobs SET status='paused' WHERE id=?", (job_id,))
                self._event(db, job_id, "paused",
                            "Прерванный запуск. Требуется явное возобновление.")

    @contextmanager
    def _connect(self):
        _no_links(self.db)
        db = sqlite3.connect(str(self.db), timeout=12)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _event(db, job_id, event, detail=""):
        db.execute("INSERT INTO journal(job_id,created,event,detail) VALUES (?,?,?,?)",
                   (job_id, _time(), event, str(detail)[:420]))

    def enqueue(self, kind, prompt="", *, approved=False, language="python",
                source_id="", allow_new_files=False):
        if approved is not True or allow_new_files is not True:
            raise PermissionError(
                "Ночная локальная генерация и запись НОВЫХ файлов требуют "
                "явного разрешения пользователя.")
        if kind not in KINDS or not isinstance(prompt, str) or len(prompt) > MAX_PROMPT_CHARS:
            raise SupervisorError("Недопустимая задача ночного режима.")
        if kind in ("scenario", "code") and len(prompt.strip()) < 3:
            raise SupervisorError("Опиши задачу хотя бы тремя символами.")
        if kind == "code" and language != "python":
            raise SupervisorError("В ночном режиме безопасно проверяется только Python.")
        if kind == "montage_advice":
            if not isinstance(source_id, str) or len(source_id) != 32 or (
                    not all(x in "0123456789abcdef" for x in source_id)):
                raise SupervisorError("Для монтажа нужен ID готового сценария.")
            prompt = ""
        elif source_id:
            raise SupervisorError("Внешние файлы и источники не разрешены.")
        with self._connect() as db:
            count = db.execute("SELECT count(*) FROM jobs WHERE status IN "
                               "('queued','running','paused')").fetchone()[0]
            if count >= MAX_JOBS:
                raise SupervisorError("Очередь заполнена. Лимит — 12 задач.")
            if kind == "montage_advice":
                origin = db.execute(
                    "SELECT kind,status FROM jobs WHERE id=?", (source_id,)).fetchone()
                if (origin is None or origin[0] != "scenario" or
                        origin[1] not in ("queued", "running", "paused", "completed")):
                    raise SupervisorError(
                        "Монтажный совет требует сценарий из этой очереди.")
            job_id = uuid4().hex
            db.execute("INSERT INTO jobs(id,kind,prompt,language,source_id,"
                       "status,step,created,approved) VALUES(?,?,?,?,?,?,?,?,?)",
                       (job_id, kind, prompt.strip(), language, source_id,
                        "queued", "new", _time(), 1))
            self._event(db, job_id, "approved",
                        "Локальная модель и только новые файлы в Night-Supervisor.")
        return job_id

    def list_jobs(self):
        with self._connect() as db:
            rows = db.execute(
                "SELECT id,kind,prompt,status,step,language,source_id,output,error "
                "FROM jobs ORDER BY created,id").fetchall()
        return tuple(NightJob(*row) for row in rows)

    def journal(self, limit=40):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Недопустимый предел журнала.")
        with self._connect() as db:
            rows = db.execute(
                "SELECT seq,job_id,created,event,detail FROM journal "
                "ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        return tuple(reversed(rows))

    def resume(self, job_id, *, approved=False):
        if approved is not True:
            raise PermissionError("Возобновление прерванной задачи требует согласия.")
        with self._connect() as db:
            row = db.execute("SELECT status,approved FROM jobs WHERE id=?",
                             (job_id,)).fetchone()
            if row != ("paused", 1):
                raise SupervisorError("Возобновлять можно только прерванную задачу.")
            db.execute("UPDATE jobs SET status='queued' WHERE id=?", (job_id,))
            self._event(db, job_id, "resumed", "Продолжение сохранённых этапов.")
        return job_id

    def _checkpoint(self, job_id, stage, payload):
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if len(raw.encode("utf-8")) > MAX_DATA_BYTES:
            raise SupervisorError("Результат превышает лимит ночной задачи.")
        digest = sha256(raw.encode("utf-8")).hexdigest()
        with self._connect() as db:
            db.execute("INSERT INTO checkpoints(job_id,step,payload,digest) "
                       "VALUES(?,?,?,?)", (job_id, stage, raw, digest))
            db.execute("UPDATE jobs SET step=? WHERE id=?", (stage, job_id))
            self._event(db, job_id, stage, "Контрольная точка сохранена.")

    def _read_checkpoint(self, job_id, stage):
        with self._connect() as db:
            row = db.execute(
                "SELECT payload,digest FROM checkpoints WHERE job_id=? AND step=?",
                (job_id, stage)).fetchone()
        if row is None or sha256(row[0].encode("utf-8")).hexdigest() != row[1]:
            raise SupervisorError("Контрольная точка отсутствует или изменена.")
        return json.loads(row[0])

    def _get_job(self, job_id):
        return next((j for j in self.list_jobs() if j.id == job_id), None)

    def _generate(self, job, progress):
        if job.kind == "scenario":
            from video_scenario_autonomy import create_checked_scenario
            from dataclasses import asdict
            brief, note, report, _ = create_checked_scenario(
                job.prompt, mode="deep", progress=lambda s: progress(s))
            if not report.passed or brief.generator != "локальная Gemma3:4b":
                raise SupervisorError("Gemma не прошла проверку; шаблон не принимается: "
                                      + str(note)[:170])
            return {"brief": asdict(brief), "model": "gemma3:4b"}
        if job.kind == "code":
            from code_project_engine import build_complete_project
            from local_coder_models import best_installed_coder
            from code_agent import request_local_model
            coder = best_installed_coder(confirmed=True)
            if coder is None:
                raise SupervisorError("Нет установленного локального Qwen Coder.")
            def generate(prompt, language):
                return request_local_model(prompt, language,
                                           endpoint="http://127.0.0.1:11434",
                                           model=coder.name)
            result = build_complete_project(
                job.prompt, "python", generator=generate, stepwise=True,
                progress=progress)
            if not result.verified:
                raise SupervisorError("Код не прошёл статическую проверку.")
            return {"model": coder.name, "language": "python",
                    "files": [{"path": x.path, "content": x.content}
                              for x in result.plan.files]}
        if job.kind == "montage_advice":
            from montage_specialist import advise_montage
            from viral_studio import load_brief
            origin = self._get_job(job.source_id)
            if origin is None or origin.status != "completed" or (
                    origin.kind != "scenario"):
                raise SupervisorError("Исходный сценарий не готов.")
            path = self.root / "outputs" / origin.id / "brief.json"
            _no_links(path)
            if not path.is_file():
                raise SupervisorError("Исходный сценарий отсутствует.")
            brief = load_brief(path)
            advice = advise_montage(brief)
            return {"model": advice.model, "text": advice.render(),
                    "shot_notes": list(advice.shot_notes)}
        raise SupervisorError("Неподдерживаемая задача.")

    @staticmethod
    def _verify(job, payload):
        if job.kind == "scenario":
            from video_scenario_autonomy import assess_scenario
            brief = _brief_from_data(payload.get("brief"))
            report = assess_scenario(brief)
            if brief.generator != "локальная Gemma3:4b" or not report.passed:
                raise SupervisorError("Независимая проверка сценария не пройдена.")
            return {"status": "passed", "verification": "structural_only",
                    "seconds": report.seconds}
        if job.kind == "code":
            from code_checks import check_project
            from code_autopilot import _stage
            from code_quality_review import review_change_plan
            plan = _plan_from_data(payload)
            if review_change_plan(plan).risk_count:
                raise SupervisorError("Код содержит потенциально опасные изменения.")
            with TemporaryDirectory(prefix="nova-night-check-") as tmp:
                folder = Path(tmp)
                _stage(plan, folder)
                report = check_project("python", folder)
            if report.get("status") != "passed" or (
                    report.get("verification") != "syntax_only"):
                raise SupervisorError("Python AST/синтаксис не прошёл проверку.")
            return {"status": "passed", "verification": "syntax_only",
                    "files": len(plan.files)}
        if job.kind == "montage_advice":
            if (payload.get("model") != "llama3.2:3b" or
                    not isinstance(payload.get("text"), str) or
                    len(payload["text"]) > 5000 or
                    not isinstance(payload.get("shot_notes"), list) or
                    len(payload["shot_notes"]) != 5 or
                    any(not isinstance(s, str) or not 4 <= len(s.strip()) <= 190
                        for s in payload["shot_notes"])):
                raise SupervisorError("Советы Llama не прошли проверку.")
            return {"status": "passed", "verification": "advice_shape_only"}
        raise SupervisorError("Неизвестный тип проверки.")

    def _save(self, job, payload):
        """Save only NEW files; a crash/partial folder blocks replay, never wipes."""
        output_base = self.root / "outputs"
        _no_links(output_base)
        output_base.mkdir(exist_ok=True)
        destination = output_base / job.id
        _no_links(destination)
        if destination.exists():
            raise SupervisorError("Выходная папка уже существует: "
                                  "не перезаписываю результаты после сбоя.")
        destination.mkdir()
        if job.kind == "code":
            from code_workspace import apply_plan
            apply_plan(_plan_from_data(payload), destination, confirmed=True)
        elif job.kind == "scenario":
            from dataclasses import asdict
            brief = _brief_from_data(payload["brief"])
            # Preserve even partial new files on failure: no rollback unlink.
            with (destination / "brief.json").open(
                    "x", encoding="utf-8") as stream:
                json.dump(asdict(brief), stream, ensure_ascii=False, indent=2)
            notes = ["# " + brief.title, "", "## Сценарий",
                     brief.script, "", "## Что снять"]
            for index, shot in enumerate(brief.shots, 1):
                notes.append(
                    f"{index:02d}. {shot.film} — {shot.seconds:g} сек. "
                    f"Текст: «{shot.caption}»")
            notes.extend(["", "Финал: " + brief.call_to_action,
                          "", "Генератор: " + brief.generator,
                          "Проверь факты, художественный результат и права."])
            with (destination / "WHAT_TO_FILM_RU.md").open(
                    "x", encoding="utf-8") as stream:
                stream.write("\n".join(notes) + "\n")
        elif job.kind == "montage_advice":
            with (destination / "MONTAGE_ADVICE_RU.md").open(
                    "x", encoding="utf-8") as stream:
                stream.write(payload["text"])
        else:
            raise SupervisorError("Неизвестный тип результата.")
        return str(destination)

    def _change_status(self, job_id, status, detail=""):
        with self._connect() as db:
            db.execute("UPDATE jobs SET status=?,error=? WHERE id=?",
                       (status, detail[:350], job_id))
            self._event(db, job_id, status, detail)

    def run_next(self, *, cancel=None, progress=None):
        """Run one task. A stopped or interrupted task never claims success."""
        if not self._run_lock.acquire(blocking=False):
            raise SupervisorError("Supervisor уже выполняет задачу.")
        try:
            if cancel is not None and cancel.is_set():
                return False
            with self._connect() as db:
                row = db.execute("SELECT id FROM jobs WHERE status='queued' "
                                 "ORDER BY created,id LIMIT 1").fetchone()
                if row is None:
                    return False
                job_id = row[0]
                db.execute("UPDATE jobs SET status='running' WHERE id=?",
                           (job_id,))
                self._event(db, job_id, "started")
            def notify(message):
                if progress is not None:
                    progress(job_id, str(message)[:350])
            try:
                job = self._get_job(job_id)
                if job.step == "new":
                    notify("Генерация: " + job.kind)
                    generated = self._executor(job, notify)
                    self._checkpoint(job_id, "generated", generated)
                    job = self._get_job(job_id)
                if cancel is not None and cancel.is_set():
                    self._change_status(job_id, "paused", "Пауза после контрольной точки.")
                    return True
                if job.step == "generated":
                    notify("Независимая проверка")
                    result = self._verify(job, self._read_checkpoint(job_id, "generated"))
                    self._checkpoint(job_id, "verified", result)
                    job = self._get_job(job_id)
                if cancel is not None and cancel.is_set():
                    self._change_status(job_id, "paused", "Пауза после проверки.")
                    return True
                if job.step == "verified":
                    notify("Сохранение новых результатов")
                    output = self._save(job, self._read_checkpoint(job_id, "generated"))
                    with self._connect() as db:
                        db.execute("UPDATE jobs SET status='completed',step='saved',"
                                   "output=?,error='' WHERE id=?", (output, job_id))
                        self._event(db, job_id, "completed", output)
                    notify("Готово: " + output)
                return True
            except Exception as exc:
                self._change_status(job_id, "blocked",
                                    type(exc).__name__ + ": " + str(exc)[:280])
                notify("Задача остановлена: " + str(exc)[:210])
                return True
        finally:
            self._run_lock.release()

    def run_queue(self, *, cancel=None, progress=None, max_minutes=360):
        if type(max_minutes) is not int or not 1 <= max_minutes <= 480:
            raise SupervisorError("Ограничение работы: от 1 до 480 минут.")
        started = time.monotonic()
        processed = 0
        while processed < MAX_JOBS and time.monotonic()-started < max_minutes*60:
            if cancel is not None and cancel.is_set():
                break
            if not self.run_next(cancel=cancel, progress=progress):
                break
            processed += 1
        return processed

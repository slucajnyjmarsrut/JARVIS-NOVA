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
from night_resource_guard import (
    memory_snapshot, under_pressure, release_specialist_memory, keep_pc_awake,
)

KINDS = ("scenario", "code", "montage_advice", "topic_video")
MAX_JOBS = 12
MAX_RESOURCE_RETRIES = 2
RESOURCE_POLL_SECONDS = 20
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
    def __init__(self, root=None, *, executor=None, memory_probe=None,
                 resource_release=None, sleeper=None, clock=None):
        self.root = Path(root if root is not None else
                         Path.home() / "JARVIS-NOVA-Projects" /
                         "Night-Supervisor").absolute()
        _no_links(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "night_jobs.sqlite3"
        _no_links(self.db)
        self._run_lock = threading.Lock()
        self._executor = executor or self._generate
        self._memory_probe = memory_probe or memory_snapshot
        self._resource_release = resource_release or release_specialist_memory
        self._sleep = sleeper or time.sleep
        self._clock = clock or time.time
        try:
            with self._process_lock(), self._connect() as db:
                self._initialize_schema(db)
        except SupervisorError as exc:
            # A long-running *approved* worker owns the lock. New UI
            # windows may still READ the existing durable queue.
            if "Другая копия JARVIS" not in str(exc) or not self.db.is_file():
                raise

    def _initialize_schema(self, db):
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, prompt TEXT NOT NULL,
                language TEXT NOT NULL, source_id TEXT NOT NULL,
                status TEXT NOT NULL, step TEXT NOT NULL,
                output TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                created TEXT NOT NULL, approved INTEGER NOT NULL,
                resource_retries INTEGER NOT NULL DEFAULT 0)""")
            # Upgrade earlier PR #6 queues without deleting any queued work.
            fields = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "resource_retries" not in fields:
                db.execute("ALTER TABLE jobs ADD COLUMN resource_retries INTEGER "
                           "NOT NULL DEFAULT 0")
            db.execute("""CREATE TABLE IF NOT EXISTS night_run (
                id INTEGER PRIMARY KEY CHECK(id=1), active INTEGER NOT NULL,
                approved INTEGER NOT NULL, deadline REAL NOT NULL)""")
            # Always-on local service is ON by default for new installations.
            # Explicit Pause stores enabled=0 and survives Windows restarts.
            db.execute("""CREATE TABLE IF NOT EXISTS background_settings (
                id INTEGER PRIMARY KEY CHECK(id=1),
                enabled INTEGER NOT NULL CHECK(enabled IN (0,1)))""")
            db.execute("INSERT OR IGNORE INTO background_settings(id,enabled) "
                       "VALUES(1,1)")
            db.execute("""CREATE TABLE IF NOT EXISTS checkpoints (
                job_id TEXT NOT NULL, step TEXT NOT NULL, payload TEXT NOT NULL,
                digest TEXT NOT NULL, PRIMARY KEY(job_id,step))""")
            db.execute("""CREATE TABLE IF NOT EXISTS journal (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                created TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL)""")
            # A bounded session was approved before the user went to sleep.
            # Recover only its earlier approved tasks while the deadline
            # still holds, never an unrelated paused/manual job.
            active = self._active_plan(db)
            ids = list(db.execute(
                "SELECT id,approved,resource_retries FROM jobs "
                "WHERE status='running'"))
            for job_id, approved, retries in ids:
                if ((active or self._background_enabled_db(db)) and
                        approved == 1 and retries <= MAX_RESOURCE_RETRIES):
                    db.execute("UPDATE jobs SET status='queued' WHERE id=?",
                               (job_id,))
                    self._event(db, job_id, "recovered",
                                "Разрешённая ночная очередь восстановлена после сбоя.")
                else:
                    db.execute("UPDATE jobs SET status='paused' WHERE id=?",
                               (job_id,))
                    self._event(db, job_id, "paused",
                                "Прерванный ручной запуск или истёкший лимит.")
            # Manually paused tasks are NEVER resumed by an old session.
            # Waiting-for-RAM tasks are eligible only under active approval.

    @contextmanager
    def _process_lock(self):
        """Exclusive OS file lock. A second JARVIS must not replay active jobs.

        The lockfile is application-owned persistent metadata. It is NEVER
        deleted; Windows/Linux release the byte lock when the process exits.
        """
        lock_path = self.root / "night_supervisor.lock"
        _no_links(lock_path)
        with lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SupervisorError(
                    "Другая копия JARVIS уже работает с ночной очередью.") from exc
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

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

    @staticmethod
    def _background_enabled_db(db):
        try:
            row = db.execute("SELECT enabled FROM background_settings WHERE id=1"
                             ).fetchone()
        except sqlite3.OperationalError:
            return False
        return bool(row and row[0] == 1)

    def background_enabled(self):
        """Always-on mode is on by default; a saved Pause disables it."""
        with self._connect() as db:
            return self._background_enabled_db(db)

    def set_background_enabled(self, enabled):
        """Persist a visible user's On/Pause choice, even when worker runs."""
        if type(enabled) is not bool:
            raise ValueError("Режим Supervisor должен быть включён или выключен.")
        with self._connect() as db:
            db.execute("UPDATE background_settings SET enabled=? WHERE id=1",
                       (int(enabled),))
            if not enabled:
                db.execute("UPDATE jobs SET status='paused' "
                           "WHERE status='waiting_memory'")
            self._event(db, "supervisor",
                        "background_enabled" if enabled else "background_paused",
                        "Следить за одобренной очередью" if enabled
                        else "Фоновая обработка остановлена до включения.")

    def background_run_next(self, *, progress=None, cancel=None):
        """Process one pre-approved task with RAM guard and OS lock.

        This is not a general agent: no newly invented tasks, arbitrary OS
        commands, user-file edits, downloads or model installation.
        """
        supervisor = self

        class StopAfterCheckpoint:
            def is_set(self):
                return ((cancel is not None and cancel.is_set()) or
                        not supervisor.background_enabled())

        with self._process_lock():
            if not self.background_enabled():
                return False
            with self._connect() as db:
                count = db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN "
                    "('queued','waiting_memory') AND approved=1").fetchone()[0]
            if not count:
                return False
            try:
                snapshot = self._memory_probe()
            except (OSError, ValueError, RuntimeError, TypeError, AttributeError):
                snapshot = None
            if under_pressure(snapshot):
                with self._connect() as db:
                    self._mark_waiting_memory(db, reason="Ожидаю свободной ОЗУ")
                self._release_memory_safely()
                return False
            with self._connect() as db:
                self._ready_after_memory(db)
            with keep_pc_awake():
                processed = self._run_next_locked(
                    cancel=StopAfterCheckpoint(), progress=progress,
                    autonomous=True)
            if processed:
                self._release_memory_safely()
            return processed

    def _active_plan(self, db):
        row = db.execute("SELECT active,approved,deadline FROM night_run "
                         "WHERE id=1").fetchone()
        return bool(row and row[0] == 1 and row[1] == 1 and
                    row[2] > self._clock())

    def run_is_approved(self):
        """Check persistent consent: safe to call during application startup."""
        with self._connect() as db:
            return self._active_plan(db)

    def approve_overnight(self, *, approved=False, max_minutes=360):
        """One upfront authorization, valid only for this bounded queue run."""
        if approved is not True:
            raise PermissionError("Нужна явная команда запустить ночную очередь.")
        if type(max_minutes) is not int or not 1 <= max_minutes <= 480:
            raise SupervisorError("Неверный ночной лимит времени.")
        with self._process_lock(), self._connect() as db:
            count = db.execute("SELECT count(*) FROM jobs WHERE status='queued' "
                               "AND approved=1").fetchone()[0]
            if not count:
                raise SupervisorError("Нет подтверждённых заданий в очереди.")
            deadline = self._clock() + 60 * max_minutes
            db.execute("INSERT INTO night_run(id,active,approved,deadline) "
                       "VALUES(1,1,1,?) ON CONFLICT(id) DO UPDATE SET "
                       "active=1,approved=1,deadline=excluded.deadline",
                       (deadline,))
            self._event(db, "night", "overnight_approved",
                        f"Лимит: {max_minutes} мин; только одобренные задания.")
        return deadline

    def stop_overnight(self):
        """Manual Stop cancels both legacy timed run and always-on restart."""
        with self._connect() as db:
            db.execute("UPDATE night_run SET active=0 WHERE id=1")
            db.execute("UPDATE background_settings SET enabled=0 WHERE id=1")
            db.execute("UPDATE jobs SET status='paused' "
                       "WHERE status='waiting_memory'")
            self._event(db, "night", "overnight_stopped",
                        "Отменено автономное продолжение после перезапуска.")

    def _finish_overnight(self, event):
        with self._connect() as db:
            db.execute("UPDATE night_run SET active=0 WHERE id=1")
            self._event(db, "night", event,
                        "Ночная сессия завершена или достигнут лимит.")

    def _release_memory_safely(self):
        # Model release is best effort: an Ollama failure cannot interrupt
        # an otherwise safely checkpointed overnight queue.
        try:
            return self._resource_release()
        except (OSError, ValueError, TypeError, RuntimeError,
                ImportError, AttributeError) as exc:
            with self._connect() as db:
                self._event(db, "night", "memory_release_unavailable",
                            type(exc).__name__)
            return 0

    def _mark_waiting_memory(self, db, *, reason="Низкий запас ОЗУ"):
        jobs = list(db.execute(
            "SELECT id FROM jobs WHERE status='queued' AND approved=1"))
        for (job_id,) in jobs:
            db.execute("UPDATE jobs SET status='waiting_memory' WHERE id=?",
                       (job_id,))
            self._event(db, job_id, "waiting_memory", reason)

    def _ready_after_memory(self, db):
        for (job_id,) in db.execute(
                "SELECT id FROM jobs WHERE status='waiting_memory' AND approved=1"):
            db.execute("UPDATE jobs SET status='queued' WHERE id=?", (job_id,))
            self._event(db, job_id, "memory_recovered",
                        "ОЗУ достаточно: продолжаю без новых вопросов.")

    def run_approved_overnight(self, *, cancel=None, progress=None):
        """Unattended resume after restart, with RAM backoff and an absolute deadline.

        Return processed count. Never extend original authorization; do not
        download anything or execute generated code. Cancellation stops
        persistent recovery as well.
        """
        with self._process_lock(), keep_pc_awake():
            with self._connect() as db:
                if not self._active_plan(db):
                    return 0
                deadline = db.execute(
                    "SELECT deadline FROM night_run WHERE id=1").fetchone()[0]
            processed = 0
            notified_pressure = False
            # Each of at most 12 jobs may have two memory retries.
            # Retries must not prematurely skip later approved jobs.
            while (self._clock() < deadline and
                   processed < MAX_JOBS * (MAX_RESOURCE_RETRIES + 1)):
                if cancel is not None and cancel.is_set():
                    self._finish_overnight("overnight_paused")
                    return processed
                with self._connect() as db:
                    if not self._active_plan(db):
                        return processed
                    active = db.execute(
                        "SELECT count(*) FROM jobs WHERE status IN "
                        "('queued','waiting_memory') AND approved=1").fetchone()[0]
                if not active:
                    with self._connect() as db:
                        blockers = db.execute(
                            "SELECT count(*) FROM jobs WHERE status='blocked'"
                        ).fetchone()[0]
                    self._finish_overnight(
                        "overnight_finished_with_blocks" if blockers else
                        "overnight_completed")
                    return processed
                try:
                    snap = self._memory_probe()
                except (OSError, ValueError, RuntimeError,
                        TypeError, AttributeError):
                    snap = None  # Unknown memory: fail closed and wait.
                if under_pressure(snap):
                    with self._connect() as db:
                        self._mark_waiting_memory(db)
                    if not notified_pressure:
                        notified_pressure = True
                        if progress is not None:
                            progress("night", "ОЗУ заканчивается: освобождаю модели "
                                     "и автоматически жду восстановления.")
                        self._release_memory_safely()
                    self._sleep(min(RESOURCE_POLL_SECONDS,
                                    max(0, deadline - self._clock())))
                    continue
                if notified_pressure:
                    notified_pressure = False
                    if progress is not None:
                        progress("night", "ОЗУ восстановлена; продолжаю очередь.")
                with self._connect() as db:
                    self._ready_after_memory(db)
                if not self._run_next_locked(
                        cancel=cancel, progress=progress, autonomous=True):
                    break
                processed += 1
                # A finished specialist must release its own residency, even
                # if the next task uses a different model.
                self._release_memory_safely()
            self._finish_overnight("overnight_deadline")
            return processed

    def enqueue(self, kind, prompt="", *, approved=False, language="python",
                source_id="", allow_new_files=False):
        if approved is not True or allow_new_files is not True:
            raise PermissionError(
                "Ночная локальная генерация и запись НОВЫХ файлов требуют "
                "явного разрешения пользователя.")
        if kind not in KINDS or not isinstance(prompt, str) or len(prompt) > MAX_PROMPT_CHARS:
            raise SupervisorError("Недопустимая задача ночного режима.")
        if kind in ("scenario", "code", "topic_video") and len(prompt.strip()) < 3:
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
            # Waiting for memory is still an outstanding approved job:
            # excluding it allowed the unattended queue to grow past 12.
            count = db.execute("SELECT count(*) FROM jobs WHERE status IN "
                               "('queued','running','paused','waiting_memory')"
                               ).fetchone()[0]
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
        if job.kind in ("scenario", "topic_video"):
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
        if job.kind in ("scenario", "topic_video"):
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

    def _save(self, job, payload, *, cancel=None):
        """Save only NEW files; a crash/partial folder blocks replay, never wipes."""
        output_base = self.root / "outputs"
        _no_links(output_base)
        output_base.mkdir(exist_ok=True)
        destination = output_base / job.id
        _no_links(destination)
        if destination.exists():
            raise SupervisorError("Выходная папка уже существует: "
                                  "не перезаписываю результаты после сбоя.")
        if job.kind == "topic_video":
            from topic_video_engine import render_topic_video
            # An interrupted render leaves no misleading final directory.
            # Rendering is staged on the SAME volume as the eventual result.
            # Temporary *JARVIS-generated* intermediates may be discarded.
            with TemporaryDirectory(prefix=".nova-topic-stage-",
                                    dir=output_base) as tmp:
                staged = Path(tmp) / "completed"
                staged.mkdir()
                _no_links(staged)
                render_topic_video(_brief_from_data(payload["brief"]), staged,
                                   cancel=cancel)
                _no_links(destination)
                if destination.exists():
                    raise SupervisorError("Выходная папка появилась; не перезаписываю.")
                staged.rename(destination)
            return str(destination)
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
        """Run one task, excluding other JARVIS processes on the same queue."""
        with self._process_lock():
            return self._run_next_locked(cancel=cancel, progress=progress)

    def _run_next_locked(self, *, cancel=None, progress=None,
                         autonomous=False):
        """The caller holds the exclusive OS lock for this whole operation."""
        if not self._run_lock.acquire(blocking=False):
            raise SupervisorError("Supervisor уже выполняет задачу.")
        try:
            if cancel is not None and cancel.is_set():
                return False
            with self._connect() as db:
                # Defense-in-depth: background mode may only execute
                # rows with an explicit per-task approval, even if the DB
                # was migrated or modified outside the supported UI.
                row = db.execute("SELECT id FROM jobs "
                                 "WHERE status='queued' AND approved=1 "
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
                    output = self._save(job, self._read_checkpoint(job_id, "generated"),
                                        cancel=cancel)
                    with self._connect() as db:
                        db.execute("UPDATE jobs SET status='completed',step='saved',"
                                   "output=?,error='' WHERE id=?", (output, job_id))
                        self._event(db, job_id, "completed", output)
                    notify("Готово: " + output)
                return True
            except (MemoryError, OSError) as exc:
                # A true OOM can be retried within the already approved
                # session. Other OS failures are not assumed to be memory.
                low_memory = (isinstance(exc, MemoryError) or
                              getattr(exc, "winerror", None) in (8, 1455))
                if autonomous and low_memory:
                    with self._connect() as db:
                        db.execute("UPDATE jobs SET resource_retries="
                                   "resource_retries+1 WHERE id=?", (job_id,))
                        count = db.execute(
                            "SELECT resource_retries FROM jobs WHERE id=?",
                            (job_id,)).fetchone()[0]
                        if count <= MAX_RESOURCE_RETRIES:
                            db.execute("UPDATE jobs SET status='waiting_memory',"
                                       "error=? WHERE id=?",
                                       ("ОЗУ исчерпана; ожидаю восстановления.", job_id))
                            self._event(db, job_id, "waiting_memory",
                                        f"Ошибка памяти; попытка {count}/{MAX_RESOURCE_RETRIES}")
                        else:
                            db.execute("UPDATE jobs SET status='blocked',error=? "
                                       "WHERE id=?", ("Превышен лимит ошибок памяти.",job_id))
                            self._event(db, job_id, "blocked", "Повторных попыток не будет.")
                    notify("Недостаточно ОЗУ: задача отложена безопасно.")
                    return True
                self._change_status(job_id, "blocked",
                                    type(exc).__name__ + ": " + str(exc)[:280])
                notify("Задача остановлена: " + str(exc)[:210])
                return True
            except Exception as exc:
                if cancel is not None and cancel.is_set():
                    # FFmpeg cancellation during a staged MP4 must pause, not
                    # mark a recoverable operation as permanently blocked.
                    self._change_status(job_id, "paused",
                                        "Остановлено после контрольной точки.")
                    notify("Генерация приостановлена; готовые файлы не тронуты.")
                    return True
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
        with self._process_lock():
            while processed < MAX_JOBS and time.monotonic()-started < max_minutes*60:
                if cancel is not None and cancel.is_set():
                    break
                if not self._run_next_locked(cancel=cancel, progress=progress):
                    break
                processed += 1
        return processed

# -*- coding: utf-8 -*-
"""Offline tests for real checkpoint persistence and approval boundaries."""
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
from contextlib import closing
import threading
import unittest
from night_supervisor import NightSupervisor, SupervisorError
from quick_video_brief import quick_brief


def screenplay(job, callback):
    brief = replace(quick_brief("minecraft"), generator="локальная Gemma3:4b")
    return {"brief": asdict(brief), "model": "gemma3:4b"}


def python_project(job, callback):
    return {"model": "qwen2.5-coder:7b", "language": "python",
            "files": [
                {"path": "calculator.py",
                 "content": "def add(a, b):\n    return a + b\n"},
                {"path": "README.md", "content": "# Calculator\n\nStatic only.\n"},
            ]}


class NightSupervisorTests(unittest.TestCase):
    def test_permission_gate_and_bounded_kinds(self):
        with TemporaryDirectory() as temp:
            s = NightSupervisor(Path(temp) / "jobs", executor=screenplay)
            with self.assertRaises(PermissionError):
                s.enqueue("scenario", "minecraft")
            with self.assertRaises(PermissionError):
                s.enqueue("scenario", "minecraft", approved=True)
            with self.assertRaises(SupervisorError):
                s.enqueue("delete", "user files", approved=True,
                          allow_new_files=True)
            with self.assertRaises(SupervisorError):
                s.enqueue("code", "build a python app", language="javascript",
                          approved=True, allow_new_files=True)
            self.assertEqual(s.list_jobs(), ())
            self.assertFalse((s.root / "outputs").exists())

    def test_real_structure_gate_then_immutable_scenario_output(self):
        with TemporaryDirectory() as temp:
            s = NightSupervisor(Path(temp) / "jobs", executor=screenplay)
            job_id = s.enqueue("scenario", "minecraft", approved=True,
                               allow_new_files=True)
            self.assertEqual(s.run_queue(), 1)
            job = s.list_jobs()[0]
            self.assertEqual(job.status, "completed", job.error)
            from viral_studio import load_brief
            self.assertEqual(load_brief(Path(job.output) / "brief.json").generator,
                             "локальная Gemma3:4b")
            self.assertTrue((Path(job.output) / "WHAT_TO_FILM_RU.md").is_file())
            self.assertIn("completed", [x[3] for x in s.journal()])
            self.assertEqual(s.run_queue(), 0)
            self.assertEqual(s.list_jobs()[0].status, "completed")

    def test_no_model_fallback_is_passed_as_success(self):
        with TemporaryDirectory() as temp:
            def template(job, callback):
                return {"brief": asdict(quick_brief("minecraft")),
                        "model": "gemma3:4b"}
            s = NightSupervisor(Path(temp) / "jobs", executor=template)
            s.enqueue("scenario", "minecraft", approved=True,
                      allow_new_files=True)
            self.assertTrue(s.run_next())
            self.assertEqual(s.list_jobs()[0].status, "blocked")
            self.assertFalse((s.root / "outputs").exists())

    def test_static_python_does_not_run_generated_code(self):
        with TemporaryDirectory() as temp:
            s = NightSupervisor(Path(temp) / "jobs", executor=python_project)
            s.enqueue("code", "Write a small calculator", approved=True,
                      allow_new_files=True)
            s.run_next()
            j = s.list_jobs()[0]
            self.assertEqual(j.status, "completed", j.error)
            self.assertTrue((Path(j.output) / "calculator.py").is_file())
            self.assertEqual(s._read_checkpoint(j.id, "verified")["verification"],
                             "syntax_only")

    def test_invalid_python_rejected_without_output(self):
        with TemporaryDirectory() as temp:
            def broken(job, cb):
                data = python_project(job, cb)
                data["files"][0]["content"] = "def wrong(:\n"
                return data
            s = NightSupervisor(Path(temp) / "jobs", executor=broken)
            s.enqueue("code", "Build an app", approved=True, allow_new_files=True)
            s.run_next()
            self.assertEqual(s.list_jobs()[0].status, "blocked")
            self.assertFalse((s.root / "outputs").exists())

    def test_resume_skips_model_generation_and_requires_approval(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "jobs"
            stop = threading.Event()
            calls = []
            def generate(job, cb):
                calls.append(1)
                stop.set()
                return screenplay(job, cb)
            s = NightSupervisor(root, executor=generate)
            job_id = s.enqueue("scenario", "minecraft",
                               approved=True, allow_new_files=True)
            s.run_next(cancel=stop)
            self.assertEqual(s.list_jobs()[0].status, "paused")
            with self.assertRaises(PermissionError):
                s.resume(job_id)
            def never_call(job, cb):
                raise AssertionError("Must reuse saved checkpoint")
            restarted = NightSupervisor(root, executor=never_call)
            restarted.resume(job_id, approved=True)
            restarted.run_next()
            self.assertEqual(restarted.list_jobs()[0].status, "completed")
            self.assertEqual(calls, [1])

    def test_running_job_after_crash_is_paused_not_replayed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "jobs"
            s = NightSupervisor(root, executor=screenplay)
            job_id = s.enqueue("scenario", "minecraft", approved=True,
                               allow_new_files=True)
            with closing(sqlite3.connect(s.db)) as db, db:
                db.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
            recovered = NightSupervisor(root, executor=screenplay)
            self.assertEqual(recovered.list_jobs()[0].status, "paused")
            self.assertFalse(recovered.run_next())

    def test_partial_output_never_overwritten(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "jobs"
            s = NightSupervisor(root, executor=python_project)
            job_id = s.enqueue("code", "A calculator", approved=True,
                               allow_new_files=True)
            folder = root / "outputs" / job_id
            folder.mkdir(parents=True)
            sentinel = folder / "calculator.py"
            sentinel.write_text("PRIVATE FILE", encoding="utf-8")
            s.run_next()
            self.assertEqual(s.list_jobs()[0].status, "blocked")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "PRIVATE FILE")

    def test_tampered_checkpoint_blocked(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "jobs"
            stop = threading.Event()
            def generator(job, cb):
                stop.set()
                return screenplay(job, cb)
            s = NightSupervisor(root, executor=generator)
            job_id = s.enqueue("scenario", "minecraft", approved=True,
                               allow_new_files=True)
            s.run_next(cancel=stop)
            with closing(sqlite3.connect(s.db)) as db, db:
                db.execute("UPDATE checkpoints SET payload='{}' WHERE job_id=?",
                           (job_id,))
            s.resume(job_id, approved=True)
            s.run_next()
            self.assertEqual(s.list_jobs()[0].status, "blocked")

    def test_montage_advice_uses_prior_scenario_only(self):
        with TemporaryDirectory() as temp:
            def executor(job, cb):
                if job.kind == "scenario":
                    return screenplay(job, cb)
                return {"model": "llama3.2:3b",
                        "text": "Советы для пяти кадров.",
                        "shot_notes": ["Отдельный ракурс кадра " + str(i)
                                       for i in range(5)]}
            s = NightSupervisor(Path(temp) / "jobs", executor=executor)
            origin = s.enqueue("scenario", "minecraft", approved=True,
                               allow_new_files=True)
            with self.assertRaises(SupervisorError):
                s.enqueue("montage_advice", source_id="f"*32,
                          approved=True, allow_new_files=True)
            s.run_next()
            s.enqueue("montage_advice", source_id=origin,
                      approved=True, allow_new_files=True)
            s.run_next()
            advice = s.list_jobs()[1]
            self.assertEqual(advice.status, "completed", advice.error)
            self.assertTrue((Path(advice.output) / "MONTAGE_ADVICE_RU.md").exists())

    def test_worker_notifications_never_call_tk_from_other_thread(self):
        from queue import Queue
        from unittest.mock import Mock
        from night_supervisor_ui import NightSupervisorWindow
        window = Mock()
        window._ui_events = Queue()
        result = []
        NightSupervisorWindow._ui(window, lambda: result.append(True))
        window.after.assert_not_called()
        window.winfo_exists.assert_not_called()
        self.assertEqual(result, [])
        NightSupervisorWindow._drain_ui(window)
        self.assertEqual(result, [True])
        window.after.assert_called_once_with(120, window._drain_ui)

    def test_second_instance_cannot_recover_while_queue_is_locked(self):
        with TemporaryDirectory() as temp:
            root = Path(temp) / "jobs"
            primary = NightSupervisor(root, executor=screenplay)
            job_id = primary.enqueue("scenario", "minecraft",
                                     approved=True, allow_new_files=True)
            with primary._process_lock():
                # A second window can inspect the existing queue without
                # pausing the live worker, but cannot run that queue itself.
                viewer = NightSupervisor(root, executor=screenplay)
                self.assertEqual(viewer.list_jobs()[0].status, "queued")
                with self.assertRaises(SupervisorError):
                    viewer.run_next()
            self.assertEqual(primary.list_jobs()[0].status, "queued")
            self.assertTrue((root / "night_supervisor.lock").exists())

    def test_montage_can_be_queued_behind_approved_scenario(self):
        with TemporaryDirectory() as temp:
            def executor(job, cb):
                if job.kind == "scenario":
                    return screenplay(job, cb)
                return {"model": "llama3.2:3b", "text": "Раздельные рекомендации.",
                        "shot_notes": ["Показать отдельный монтажный ракурс"
                                       for _ in range(5)]}
            manager = NightSupervisor(Path(temp) / "jobs", executor=executor)
            origin = manager.enqueue("scenario", "minecraft",
                                     approved=True, allow_new_files=True)
            manager.enqueue("montage_advice", source_id=origin,
                            approved=True, allow_new_files=True)
            self.assertEqual(manager.run_queue(), 2)
            self.assertEqual(tuple(j.status for j in manager.list_jobs()),
                             ("completed", "completed"))

    def test_symlink_root_denied(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "real"
            original.mkdir()
            alias = root / "link"
            try:
                alias.symlink_to(original, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink unavailable")
            with self.assertRaises(SupervisorError):
                NightSupervisor(alias)


if __name__ == "__main__":
    unittest.main()

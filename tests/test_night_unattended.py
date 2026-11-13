# -*- coding: utf-8 -*-
"""Fully offline deterministic tests for unattended work after RAM pressure/crash.

No real models, network, sleep, OS shutdown, delete, or generated code execution.
"""
from dataclasses import asdict, replace
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock
import sqlite3
import unittest

from night_resource_guard import (
    MemorySnapshot, MIB, under_pressure, release_specialist_memory,
)
from night_supervisor import NightSupervisor, SupervisorError
from quick_video_brief import quick_brief


def generated_scenario(job, progress):
    return {"brief": asdict(replace(quick_brief("minecraft"),
                                    generator="локальная Gemma3:4b")),
            "model": "gemma3:4b"}


class Clock:
    def __init__(self):
        self.now = 1000.
        self.sleeps = []
    def time(self):
        return self.now
    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class UnattendedRecoveryTests(unittest.TestCase):
    def create(self, root, **kwargs):
        return NightSupervisor(
            root, executor=kwargs.pop("executor", generated_scenario),
            clock=kwargs.pop("clock", Clock().time),
            memory_probe=kwargs.pop(
                "memory_probe",
                lambda: MemorySnapshot(4_000*MIB, 8_000*MIB)),
            sleeper=kwargs.pop("sleeper", lambda s: None),
            resource_release=kwargs.pop("resource_release", lambda: 0),
            **kwargs)

    def new_job(self, supervisor):
        return supervisor.enqueue("scenario", "minecraft", approved=True,
                                  allow_new_files=True)

    def test_unapproved_run_never_starts(self):
        with TemporaryDirectory() as temp:
            executed = []
            def executor(job, progress):
                executed.append(job.id)
                return generated_scenario(job, progress)
            s = self.create(Path(temp)/"night", executor=executor)
            self.new_job(s)
            self.assertFalse(s.run_is_approved())
            self.assertEqual(s.run_approved_overnight(), 0)
            self.assertEqual(executed, [])
            self.assertEqual(s.list_jobs()[0].status, "queued")
            with self.assertRaises(PermissionError):
                s.approve_overnight()

    def test_memory_pressure_unloads_models_waits_then_finishes_by_itself(self):
        with TemporaryDirectory() as temp:
            clock = Clock()
            low = MemorySnapshot(40*MIB, 8_000*MIB)
            ok = MemorySnapshot(4_000*MIB, 8_000*MIB)
            samples = iter((low, low, ok))
            freed = []
            s = self.create(Path(temp)/"night", clock=clock.time,
                            sleeper=clock.sleep,
                            memory_probe=lambda: next(samples, ok),
                            resource_release=lambda: freed.append(1))
            self.new_job(s)
            s.approve_overnight(approved=True, max_minutes=4)
            self.assertEqual(s.run_approved_overnight(), 1)
            self.assertEqual(s.list_jobs()[0].status, "completed")
            self.assertFalse(s.run_is_approved())
            events = [row[3] for row in s.journal()]
            self.assertIn("waiting_memory", events)
            self.assertIn("memory_recovered", events)
            self.assertIn("overnight_completed", events)
            self.assertGreaterEqual(len(clock.sleeps), 2)
            self.assertGreaterEqual(len(freed), 2)

    def test_low_ram_never_exhausts_retries_or_loops_forever(self):
        with TemporaryDirectory() as temp:
            clock = Clock()
            executed = []
            def executor(job, progress):
                executed.append(job.id)
                return generated_scenario(job, progress)
            s = self.create(Path(temp)/"night", clock=clock.time,
                            sleeper=clock.sleep, executor=executor,
                            memory_probe=lambda: MemorySnapshot(1*MIB, 8_000*MIB))
            self.new_job(s)
            s.approve_overnight(approved=True, max_minutes=1)
            self.assertEqual(s.run_approved_overnight(), 0)
            self.assertEqual(executed, [])
            self.assertEqual(s.list_jobs()[0].status, "waiting_memory")
            self.assertFalse(s.run_is_approved())
            self.assertLessEqual(sum(clock.sleeps), 60)
            self.assertIn("overnight_deadline", [row[3] for row in s.journal()])

    def test_authorized_crash_can_resume_without_human_prompt(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)/"night"
            clock = Clock()
            s = self.create(root, clock=clock.time)
            job_id = self.new_job(s)
            s.approve_overnight(approved=True, max_minutes=360)
            with closing(sqlite3.connect(s.db)) as db, db:
                db.execute("UPDATE jobs SET status='running' WHERE id=?",
                           (job_id,))
            recovered = self.create(root, clock=clock.time)
            self.assertEqual(recovered.list_jobs()[0].status, "queued")
            self.assertEqual(recovered.run_approved_overnight(), 1)
            self.assertEqual(recovered.list_jobs()[0].status, "completed")
            self.assertIn("recovered", [row[3] for row in recovered.journal()])

    def test_expired_timed_session_does_not_restart_timed_run(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)/"night"
            clock = Clock()
            s = self.create(root, clock=clock.time)
            job_id = self.new_job(s)
            s.approve_overnight(approved=True, max_minutes=1)
            with closing(sqlite3.connect(s.db)) as db, db:
                db.execute("UPDATE jobs SET status='running' WHERE id=?",
                           (job_id,))
            clock.now += 61
            recovered = self.create(root, clock=clock.time)
            # The expired *timed session* cannot restart itself.
            # An individually approved job remains eligible only through
            # the separate always-on per-task mode.
            self.assertEqual(recovered.list_jobs()[0].status, "queued")
            self.assertEqual(recovered.run_approved_overnight(), 0)
            self.assertTrue(recovered.background_run_next())
            self.assertEqual(recovered.list_jobs()[0].status, "completed")

    def test_manual_stop_disables_automatic_restart(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)/"night"
            clock = Clock()
            s = self.create(root, clock=clock.time)
            job_id = self.new_job(s)
            s.approve_overnight(approved=True, max_minutes=360)
            s.stop_overnight()
            with closing(sqlite3.connect(s.db)) as db, db:
                db.execute("UPDATE jobs SET status='running' WHERE id=?",
                           (job_id,))
            reopened = self.create(root, clock=clock.time)
            self.assertEqual(reopened.list_jobs()[0].status, "paused")
            self.assertFalse(reopened.run_is_approved())
            self.assertEqual(reopened.run_approved_overnight(), 0)

    def test_memory_error_is_retried_automatically_but_bounded(self):
        with TemporaryDirectory() as temp:
            attempts = []
            def flaky(job, progress):
                attempts.append(1)
                if len(attempts) == 1:
                    raise MemoryError("Out of memory")
                return generated_scenario(job, progress)
            s = self.create(Path(temp)/"night", executor=flaky)
            self.new_job(s)
            s.approve_overnight(approved=True, max_minutes=60)
            self.assertEqual(s.run_approved_overnight(), 2)
            self.assertEqual(len(attempts), 2)
            self.assertEqual(s.list_jobs()[0].status, "completed")

    def test_repeated_memory_errors_block_instead_of_infinite_loop(self):
        with TemporaryDirectory() as temp:
            attempts = []
            def fail(job, progress):
                attempts.append(1)
                raise MemoryError()
            s = self.create(Path(temp)/"night", executor=fail)
            self.new_job(s)
            s.approve_overnight(approved=True, max_minutes=60)
            self.assertEqual(s.run_approved_overnight(), 3)
            self.assertEqual(len(attempts), 3)
            self.assertEqual(s.list_jobs()[0].status, "blocked")
            self.assertFalse(s.run_is_approved())

    def test_guard_denies_missing_metrics_and_low_ram(self):
        self.assertTrue(under_pressure(None))
        self.assertTrue(under_pressure(MemorySnapshot(200*MIB, 4_000*MIB)))
        self.assertFalse(under_pressure(MemorySnapshot(3_000*MIB, 4_000*MIB)))

    def test_model_unloader_is_allowlisted_and_does_not_kill_processes(self):
        from task_ai_registry import get_specialist
        calls = []
        total = release_specialist_memory(sender=calls.append)
        self.assertEqual(total, 3)
        self.assertEqual(set(calls), {
            get_specialist(x).model for x in ("scenario", "code", "montage")
        })

    def test_startup_module_does_not_do_anything_without_queue_file(self):
        from night_autorecovery import start_if_approved
        with TemporaryDirectory() as temp:
            factory = Mock()
            result = start_if_approved(Path(temp)/"absent",
                                       supervisor_factory=factory)
            self.assertIsNone(result)
            factory.assert_not_called()

    def test_startup_worker_requires_existing_unexpired_session(self):
        from night_autorecovery import start_if_approved
        with TemporaryDirectory() as temp:
            root = Path(temp)/"night"
            clock = Clock()
            s = self.create(root, clock=clock.time)
            job_id = self.new_job(s)
            s.approve_overnight(approved=True, max_minutes=360)
            worker = start_if_approved(root, supervisor_factory=lambda p: self.create(
                p, clock=clock.time))
            self.assertIsNotNone(worker)
            worker.join(timeout=6)
            self.assertFalse(worker.is_alive())
            self.assertEqual(self.create(root, clock=clock.time).
                             list_jobs()[0].status, "completed")


if __name__ == "__main__":
    unittest.main()

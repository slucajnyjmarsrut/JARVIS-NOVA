# -*- coding: utf-8 -*-
"""Always-on Supervisor contract without real models, registry or network."""
from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, mock
import os
import sqlite3
import threading
import unittest
import sys

from night_resource_guard import MIB, MemorySnapshot
from night_supervisor import NightSupervisor
from night_supervisor_service import run_forever
from quick_video_brief import quick_brief


def _scenario(job, progress):
    return {"brief": asdict(replace(quick_brief("Minecraft"),
                                    generator="локальная Gemma3:4b")),
            "model": "gemma3:4b"}


def _manager(root, **kwargs):
    return NightSupervisor(root, executor=kwargs.pop("executor", _scenario),
                           memory_probe=kwargs.pop("memory_probe",
                               lambda: MemorySnapshot(8_000*MIB, 16_000*MIB)),
                           resource_release=kwargs.pop("resource_release",
                               lambda: 0), **kwargs)


class AlwaysOnSupervisorTests(TestCase):
    def test_default_works_without_start_button_but_never_creates_jobs(self):
        with TemporaryDirectory() as tmp:
            s=_manager(Path(tmp)/"night")
            self.assertTrue(s.background_enabled())
            self.assertFalse(s.background_run_next())
            self.assertEqual(s.list_jobs(), ())

    def test_unapproved_queue_row_cannot_execute_even_if_db_is_modified(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"night"
            executed=[]
            def execute(job,cb):
                executed.append(job.id)
                return _scenario(job,cb)
            s=_manager(root,executor=execute)
            job_id=s.enqueue("scenario","Minecraft",approved=True,
                             allow_new_files=True)
            with closing(sqlite3.connect(s.db)) as db, db:
                db.execute("UPDATE jobs SET approved=0 WHERE id=?",(job_id,))
            self.assertFalse(s.background_run_next())
            self.assertEqual(executed,[])
            self.assertEqual(s.list_jobs()[0].status,"queued")

    def test_memory_waiting_jobs_still_count_toward_queue_limit(self):
        from night_supervisor import SupervisorError
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"night"
            s=_manager(root)
            for i in range(12):
                s.enqueue("scenario",f"Minecraft project {i}",
                          approved=True,allow_new_files=True)
            with closing(sqlite3.connect(s.db)) as db, db:
                db.execute("UPDATE jobs SET status='waiting_memory'")
            with self.assertRaises(SupervisorError):
                s.enqueue("scenario","13th Minecraft project",
                          approved=True,allow_new_files=True)
            self.assertEqual(len(s.list_jobs()),12)

    def test_only_explicitly_approved_job_runs_automatically(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"night"
            seen=[]
            def execute(job, cb):
                seen.append(job.id)
                return _scenario(job, cb)
            s=_manager(root, executor=execute)
            with self.assertRaises(PermissionError):
                s.enqueue("scenario","Minecraft")
            self.assertFalse(s.background_run_next())
            job_id=s.enqueue("scenario","Minecraft",approved=True,
                             allow_new_files=True)
            self.assertTrue(s.background_run_next())
            self.assertEqual(seen,[job_id])
            self.assertEqual(s.list_jobs()[0].status,"completed")
            self.assertFalse(s.background_run_next())

    def test_pause_is_persisted_and_prevents_scheduled_jobs(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"night"
            s=_manager(root)
            job_id=s.enqueue("scenario","Minecraft",approved=True,
                             allow_new_files=True)
            s.set_background_enabled(False)
            self.assertFalse(_manager(root).background_enabled())
            self.assertFalse(_manager(root).background_run_next())
            self.assertEqual(s.list_jobs()[0].status,"queued")
            _manager(root).set_background_enabled(True)
            self.assertTrue(_manager(root).background_run_next())
            self.assertEqual(_manager(root).list_jobs()[0].status,"completed")

    def test_no_automatic_resume_after_explicit_pause_before_restart(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"night"
            s=_manager(root)
            id=s.enqueue("scenario","Minecraft",approved=True,
                         allow_new_files=True)
            s.set_background_enabled(False)
            with closing(sqlite3.connect(s.db)) as db, db:
                db.execute("UPDATE jobs SET status='running' WHERE id=?", (id,))
            restarted=_manager(root)
            self.assertEqual(restarted.list_jobs()[0].status,"paused")
            self.assertFalse(restarted.background_enabled())

    def test_recover_running_task_after_crash_when_background_on(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"night"
            s=_manager(root)
            job_id=s.enqueue("scenario","Minecraft",approved=True,
                             allow_new_files=True)
            with closing(sqlite3.connect(s.db)) as db, db:
                db.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
            again=_manager(root)
            self.assertEqual(again.list_jobs()[0].status,"queued")
            self.assertTrue(again.background_run_next())
            self.assertEqual(again.list_jobs()[0].status,"completed")

    def test_low_ram_waits_without_writing_any_result_then_resumes(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"night"
            freed=[]
            state={"low":True}
            def memory():
                return (MemorySnapshot(30*MIB, 8_000*MIB) if state["low"]
                        else MemorySnapshot(4_000*MIB, 8_000*MIB))
            s=_manager(root, memory_probe=memory,
                       resource_release=lambda:freed.append(True))
            s.enqueue("scenario","Minecraft",approved=True,
                      allow_new_files=True)
            self.assertFalse(s.background_run_next())
            self.assertEqual(s.list_jobs()[0].status,"waiting_memory")
            self.assertEqual(len(freed),1)
            state["low"]=False
            self.assertTrue(s.background_run_next())
            self.assertEqual(s.list_jobs()[0].status,"completed")

    def test_repeated_real_memory_errors_have_fixed_retry_limit(self):
        with TemporaryDirectory() as tmp:
            count=[]
            def oom(job, cb):
                count.append(job.id)
                raise MemoryError()
            s=_manager(Path(tmp)/"night",executor=oom)
            s.enqueue("scenario","Minecraft",approved=True,
                      allow_new_files=True)
            for _ in range(8):
                s.background_run_next()
            self.assertEqual(len(count),3)
            self.assertEqual(s.list_jobs()[0].status,"blocked")
            self.assertFalse(s.background_run_next())

    def test_manual_pause_is_seen_at_checkpoint_without_killing_model(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"night"
            def while_running(job, cb):
                controller.set_background_enabled(False)
                return _scenario(job,cb)
            controller=_manager(root,executor=while_running)
            controller.enqueue("scenario","Minecraft",approved=True,
                               allow_new_files=True)
            self.assertTrue(controller.background_run_next())
            self.assertEqual(controller.list_jobs()[0].status,"paused")
            self.assertFalse(controller.background_enabled())

    def test_service_loop_watches_empty_queue_without_busy_loop_or_invention(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"night"
            manager=_manager(root)
            events=threading.Event()
            polls=[]
            def wait(seconds):
                polls.append(seconds)
                if len(polls)>=3:
                    events.set()
                return True
            with mock.patch.object(events,"wait",side_effect=wait):
                run_forever(root,supervisor_factory=lambda _:manager,
                            stop_event=events,poll_seconds=5)
            self.assertEqual(polls,[5,5,5])
            self.assertEqual(manager.list_jobs(),())

    def test_service_loop_does_not_run_jobs_when_paused(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"night"
            manager=_manager(root)
            manager.enqueue("scenario","Minecraft",approved=True,
                            allow_new_files=True)
            manager.set_background_enabled(False)
            stop=threading.Event()
            with mock.patch.object(stop,"wait",side_effect=lambda secs:stop.set()):
                run_forever(root,supervisor_factory=lambda _:manager,
                            stop_event=stop,poll_seconds=1)
            self.assertEqual(manager.list_jobs()[0].status,"queued")

    def test_frozen_launcher_has_literal_argv_and_no_shell(self):
        from night_autorecovery import start_always_on
        import night_autorecovery
        spawn=mock.Mock()
        with mock.patch.object(night_autorecovery,"_spawned",False), mock.patch(
                "night_autorecovery.os.name","nt"), mock.patch.object(
                sys,"frozen",True,create=True), mock.patch.object(
                sys,"executable",r"C:\Program Files\JarvisNova\JarvisNova.exe"):
            start_always_on(popen=spawn)
        spawn.assert_called_once()
        argv=spawn.call_args.args[0]
        self.assertEqual(argv, [r"C:\Program Files\JarvisNova\JarvisNova.exe",
                                "--supervisor-daemon"])
        self.assertNotIn("shell",spawn.call_args.kwargs)

    def test_bootstrap_daemon_has_separate_mutex_and_no_tk_entrypoint(self):
        import bootstrap
        with mock.patch.object(sys,"argv",["JarvisNova.exe","--supervisor-daemon"]), mock.patch(
                "bootstrap._acquire_windows_single_instance",
                return_value=False) as mutex, mock.patch(
                "night_supervisor_service.run_forever") as worker:
            self.assertEqual(bootstrap.main(),0)
            mutex.assert_called_once_with("JarvisNovaSupervisorDaemon")
            worker.assert_not_called()


if __name__=="__main__":
    unittest.main()

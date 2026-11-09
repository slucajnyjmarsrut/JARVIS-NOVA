# -*- coding: utf-8 -*-
"""Integration tests for app-like background updates and safe idle restarts."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import io
from pathlib import Path
import queue
import tempfile
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock

from auto_update import Release, download_release
from update_preferences import (
    UpdatePreferences, load_preferences, save_preferences,
)


class PreferencesTests(unittest.TestCase):
    def test_defaults_and_persistent_user_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"prefs"/"update_preferences.json"
            self.assertEqual(load_preferences(path),UpdatePreferences(True,False))
            saved=UpdatePreferences(False,False)
            self.assertEqual(save_preferences(saved,path),path)
            self.assertEqual(load_preferences(path),saved)
            self.assertEqual(list(path.parent.glob("*.tmp")),[])
            self.assertTrue(path.read_text().startswith("{"))

    def test_legacy_preferences_cannot_silently_enable_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"update_preferences.json"
            path.write_text(
                '{"schema":1,"automatic_checks":true,"automatic_restart":true}',
                encoding="utf-8")
            self.assertEqual(load_preferences(path), UpdatePreferences(True,False))
            path.write_text(
                '{"automatic_checks":true,"automatic_restart":true}',
                encoding="utf-8")
            self.assertEqual(load_preferences(path), UpdatePreferences(True,False))
            explicit=UpdatePreferences(True,True)
            save_preferences(explicit,path)
            self.assertEqual(load_preferences(path), explicit)
            self.assertIn('"schema":2', path.read_text(encoding="utf-8"))

    def test_untrusted_settings_do_not_enable_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"opts.json"
            for data in (
                '{"automatic_checks":"true","automatic_restart":false}',
                '{"automatic_checks":1,"automatic_restart":0}',
                '[]', '{invalid json',
            ):
                path.write_text(data,encoding="utf-8")
                self.assertEqual(load_preferences(path),
                                 UpdatePreferences(False,False))
            with self.assertRaises(ValueError):
                save_preferences(UpdatePreferences(True,"yes"),path)
            if hasattr(Path,"symlink_to"):
                outside=Path(directory)/"outside.json"
                outside.write_text("protected",encoding="utf-8")
                link=Path(directory)/"linked.json"
                try:
                    link.symlink_to(outside)
                except (OSError,NotImplementedError):
                    return
                with self.assertRaises(OSError):
                    save_preferences(UpdatePreferences(),link)
                self.assertEqual(outside.read_text(encoding="utf-8"),"protected")


class UpdateDownloadTests(unittest.TestCase):
    def test_verified_download_emits_progress_and_reuses_cached_file(self):
        blob=b"MZ"+b"x"*110_000
        version="0.5.19"
        name=f"JARVIS-NOVA-{version}-OFFLINE-SETUP.exe"
        url=f"https://github.com/slucajnyjmarsrut/JARVIS-NOVA/releases/download/v{version}/{name}"
        release=Release(version,name,url,hashlib.sha256(blob).hexdigest(),len(blob))
        class Opener:
            def open(self,request,timeout):
                self_test.assertEqual(request.full_url,url)
                return io.BytesIO(blob)
        self_test=self
        with tempfile.TemporaryDirectory() as tmp:
            progress=[]
            dest=download_release(release,Path(tmp),opener=Opener(),
                                  progress=lambda done,total: progress.append((done,total)))
            self.assertEqual(dest.read_bytes(),blob)
            self.assertTrue(progress)
            self.assertEqual(progress[-1],(len(blob),len(blob)))
            reused=download_release(release,Path(tmp),
                opener=mock.Mock(open=mock.Mock(side_effect=AssertionError("no fetch"))),
                progress=lambda done,total: progress.append((done,total)))
            self.assertEqual(reused,dest)
            self.assertEqual(progress[-1],(len(blob),len(blob)))


class AutoUpdateControllerTests(unittest.TestCase):
    @staticmethod
    def fake_app():
        version="0.5.19"
        return SimpleNamespace(
            _closing=False,_auto_update_busy=False,
            _auto_update_pending=(SimpleNamespace(version=version),
                                  Path("C:/Cache/candidate-0.5.19.exe")),
            _auto_update_first_seen=time.monotonic()-800,
            _last_input_activity=time.monotonic(),
            _auto_update_snoozed=False,
            update_preferences=UpdatePreferences(True,True),
            executing=False,
            _viral_window=SimpleNamespace(running=False),
            speaker=SimpleNamespace(busy=False),
            trimodal=SimpleNamespace(speaking=False),
            voice=SimpleNamespace(whisper_busy=False),
            entry=SimpleNamespace(get=lambda:""),
            after=mock.Mock(),_finish_auto_update=mock.Mock(),
            status=SimpleNamespace(set=mock.Mock()),
            close=mock.Mock(),q=queue.Queue(),_shutdown=mock.Mock()
        )

    def test_no_restart_while_typing_or_recent_activity(self):
        from main import Jarvis
        app=self.fake_app()
        with mock.patch("main.installed_application",
                        return_value=Path("C:/App/JarvisNova.exe")), \
             mock.patch("main.stage_helper") as stage:
            Jarvis._finish_auto_update(app)
            stage.assert_not_called()
            app.after.assert_called_once()
            app.entry=SimpleNamespace(get=lambda:"unsent video script")
            Jarvis._finish_auto_update(app,force=True)
            stage.assert_not_called()
            app.entry=SimpleNamespace(get=lambda:"")
            app._last_input_activity=time.monotonic()-800
            app.update_preferences=UpdatePreferences(True,False)
            Jarvis._finish_auto_update(app)
            stage.assert_not_called()
            app._auto_update_snoozed=True
            app.update_preferences=UpdatePreferences()
            Jarvis._finish_auto_update(app)
            stage.assert_not_called()
            Jarvis._finish_auto_update(app,force=True)
            stage.assert_called_once()
            app.close.assert_called_once()

    def test_offline_python_run_cannot_contact_update_server(self):
        from main import Jarvis
        app=self.fake_app()
        app._auto_update_pending=None
        app.update_preferences=UpdatePreferences(False,False)
        with mock.patch("main.installed_application",return_value=None), \
             mock.patch("main.check_and_download") as downloader:
            Jarvis._check_auto_update(app)
            Jarvis._check_auto_update(app,force=True)
            downloader.assert_not_called()
            self.assertIn("установленном Windows",app._auto_update_state)


class UpdateCenterGuiTests(unittest.TestCase):
    def test_untrusted_publisher_disables_manual_install_and_check(self):
        from update_center import UpdateCenter
        app=SimpleNamespace(
            _auto_update_pending=(object(), Path("C:/updates/fake.exe")),
            _check_auto_update=mock.Mock(),
            _finish_auto_update=mock.Mock())
        fake=SimpleNamespace(app=app,status=SimpleNamespace(set=mock.Mock()),
                             refresh=mock.Mock())
        with mock.patch("update_center.publisher_is_configured",return_value=False):
            UpdateCenter.check(fake)
            UpdateCenter.install(fake)
        app._check_auto_update.assert_not_called()
        app._finish_auto_update.assert_not_called()
        fake.status.set.assert_called()
        fake.refresh.assert_not_called()

    def test_dark_center_controls_callbacks(self):
        from update_center import UpdateCenter
        try:
            app=tk.Tk()
        except tk.TclError as exc:
            self.skipTest("No display: "+str(exc))
        try:
            app.withdraw()
            app.update_preferences=UpdatePreferences(True,True)
            app._auto_update_pending=None
            app._auto_update_state="Новых релизов нет."
            app._auto_update_progress=0
            app._auto_update_busy=False
            app._auto_update_snoozed=False
            app._check_auto_update=mock.Mock()
            app._finish_auto_update=mock.Mock()
            with tempfile.TemporaryDirectory() as tmp, \
                 mock.patch("update_center.publisher_is_configured", return_value=True), \
                 mock.patch("update_center.save_preferences",
                     side_effect=lambda value:save_preferences(value,
                         Path(tmp)/"choices.json")):
                view=UpdateCenter(app)
                app.update_idletasks()
                self.assertEqual(view.cget("bg"),"#081421")
                view.auto_check.set(False)
                view.save()
                self.assertFalse(app.update_preferences.automatic_checks)
                view.check()
                app._check_auto_update.assert_called_once_with(force=True)
                view.later()
                self.assertTrue(app._auto_update_snoozed)
                app._auto_update_pending=(object(),Path(tmp)/"ready.exe")
                view.install()
                app._finish_auto_update.assert_called_once_with(force=True)
                self.assertTrue((Path(tmp)/"choices.json").exists())
                view.destroy()
        finally:
            app.destroy()


if __name__=="__main__":
    unittest.main()

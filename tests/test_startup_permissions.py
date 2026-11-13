# -*- coding: utf-8 -*-
"""Explicit opt-in and protected Windows startup permission regression."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import os
import unittest
from startup_permissions import (
    StartupPermissions, load_startup_permissions, save_startup_permissions,
)
from main import Jarvis


class StartupPermissionsTests(unittest.TestCase):
    def test_missing_file_defaults_disabled(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(load_startup_permissions(Path(tmp)/"none.bin"),
                             StartupPermissions())
            self.assertFalse(StartupPermissions().control)
            self.assertFalse(StartupPermissions().vision)

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_windows_dpapi_roundtrip_and_revoke(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/"permissions.bin"
            save_startup_permissions(StartupPermissions(True, True), p)
            self.assertEqual(load_startup_permissions(p),
                             StartupPermissions(True, True))
            self.assertNotIn(b'"control"', p.read_bytes())
            save_startup_permissions(StartupPermissions(False, False), p)
            self.assertEqual(load_startup_permissions(p), StartupPermissions())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_tampered_and_unprotected_file_never_grants(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/"permissions.bin"
            p.write_text('{"schema":1,"approved":true,"control":true,"vision":true}',
                         encoding="utf-8")
            self.assertEqual(load_startup_permissions(p), StartupPermissions())
            p.write_bytes(b"a"*2200)
            self.assertEqual(load_startup_permissions(p), StartupPermissions())
            p.write_bytes(b"")
            self.assertEqual(load_startup_permissions(p), StartupPermissions())

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_old_schema_protected_data_not_trusted(self):
        from startup_permissions import _dpapi
        with TemporaryDirectory() as tmp:
            p = Path(tmp)/"permissions.bin"
            source = b'{"schema":0,"scope":"control+vision","approved":true,"control":true,"vision":true}'
            p.write_bytes(_dpapi(source, encrypt=True))
            self.assertEqual(load_startup_permissions(p), StartupPermissions())

    def test_cancel_does_not_store_or_enable(self):
        app = Mock()
        app.control_allowed = False
        app.vision_allowed = False
        with patch("main.messagebox.askyesno", return_value=False), patch(
                "startup_permissions.save_startup_permissions") as save:
            self.assertFalse(Jarvis.enable_persistent_permissions(app))
            save.assert_not_called()
        self.assertFalse(app.control_allowed)
        self.assertFalse(app.vision_allowed)

    def test_confirm_saves_both_scopes(self):
        app = Mock()
        app.control_allowed = False
        app.vision_allowed = False
        with patch("main.messagebox.askyesno", return_value=True), patch(
                "startup_permissions.save_startup_permissions") as save:
            self.assertTrue(Jarvis.enable_persistent_permissions(app))
            save.assert_called_once_with(StartupPermissions(True, True))
        self.assertTrue(app.control_allowed)
        self.assertTrue(app.vision_allowed)

    def test_failed_save_does_not_enable(self):
        app = Mock()
        app.control_allowed = False
        app.vision_allowed = False
        with patch("main.messagebox.askyesno", return_value=True), patch(
                "startup_permissions.save_startup_permissions",
                side_effect=OSError("denied")), patch("main.messagebox.showerror"):
            self.assertFalse(Jarvis.enable_persistent_permissions(app))
        self.assertFalse(app.control_allowed)
        self.assertFalse(app.vision_allowed)

    def test_restoring_only_known_scopes_has_no_actions(self):
        app = Mock()
        app.control_allowed = False
        app.vision_allowed = False
        with patch("startup_permissions.load_startup_permissions",
                   return_value=StartupPermissions(True, True)):
            Jarvis._restore_startup_permissions(app)
        self.assertTrue(app.control_allowed)
        self.assertTrue(app.vision_allowed)
        app.desktop.click.assert_not_called()
        app.desktop.screenshot.assert_not_called()
        with patch("startup_permissions.load_startup_permissions",
                   return_value=StartupPermissions()):
            Jarvis._restore_startup_permissions(app)
        self.assertFalse(app.control_allowed)
        self.assertFalse(app.vision_allowed)

    def test_revoke_removes_saved_and_live_permission(self):
        app = Mock()
        app.control_allowed = True
        app.vision_allowed = True
        with patch("startup_permissions.save_startup_permissions") as save:
            self.assertTrue(Jarvis.revoke(app))
            save.assert_called_once_with(StartupPermissions(False, False))
        self.assertFalse(app.control_allowed)
        self.assertFalse(app.vision_allowed)

    def test_revoke_failure_warns_does_not_claim_persisted_revocation(self):
        app = Mock()
        app.control_allowed = True
        app.vision_allowed = True
        with patch("startup_permissions.save_startup_permissions",
                   side_effect=OSError("locked")), patch(
                   "main.messagebox.showerror") as notify:
            self.assertFalse(Jarvis.revoke(app))
            notify.assert_called_once()
        self.assertFalse(app.control_allowed)
        self.assertFalse(app.vision_allowed)

    def test_saved_vision_grant_avoids_repeat_screen_capture_prompt(self):
        app = Mock()
        app._closing = False
        app.executing = False
        app.vision_allowed = True
        app.voice_enabled = False
        with patch("main.messagebox.askyesno") as ask, patch(
                "main.threading.Thread") as worker:
            Jarvis.request_trimodal(app, "screen")
            ask.assert_not_called()
            worker.assert_called_once()
            worker.return_value.start.assert_called_once()
        self.assertTrue(app.executing)

    def test_without_vision_permission_screen_capture_can_be_denied(self):
        app = Mock()
        app._closing = False
        app.executing = False
        app.vision_allowed = False
        with patch("main.messagebox.askyesno", return_value=False) as ask, patch(
                "main.threading.Thread") as worker:
            Jarvis.request_trimodal(app, "screen")
            ask.assert_called_once()
            worker.assert_not_called()
        self.assertFalse(app.executing)

    def test_bad_permission_inputs_rejected(self):
        with self.assertRaises(ValueError):
            save_startup_permissions(StartupPermissions(1, True))
        with self.assertRaises(ValueError):
            save_startup_permissions({"control": True, "vision": True})


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Regression tests for safe, bounded, non-code-modifying self-repair."""
import errno
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

from self_repair import (RepairError, inspect_configs, repair_configs,
                         retry_readonly)


class SelfRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)

    def test_never_mutate_files_without_confirmation(self):
        settings=self.folder/"learning-v1.json"
        settings.write_text("{corrupt",encoding="utf-8")
        before=settings.read_bytes()
        self.assertEqual(inspect_configs(self.folder)[0].status,"corrupt")
        with self.assertRaises(PermissionError):
            repair_configs(folder=self.folder)
        self.assertEqual(settings.read_bytes(),before)
        self.assertEqual(list(self.folder.iterdir()),[settings])

    def test_valid_files_and_missing_files_are_not_reset(self):
        path=self.folder/"learning-v1.json"
        text=json.dumps({"version":1,"aliases":{"стим":"Steam"},"stats":{}})
        path.write_text(text,encoding="utf-8")
        found=inspect_configs(self.folder)
        self.assertEqual(found[0].status,"healthy")
        self.assertEqual(found[1].status,"absent")
        result=repair_configs(consent=True,folder=self.folder)
        self.assertEqual(result.repaired,())
        self.assertEqual(path.read_text("utf-8"),text)
        self.assertFalse(list(self.folder.glob("*.bak")))

    def test_repairs_two_corrupted_configs_with_exclusive_backups(self):
        learning=self.folder/"learning-v1.json"
        modes=self.folder/"modes-v1.json"
        original_one=b'INVALID{'
        original_two=b'{"version":1,"apps":[]} '
        learning.write_bytes(original_one)
        modes.write_bytes(original_two)
        report=repair_configs(consent=True,folder=self.folder)
        self.assertCountEqual(report.repaired,["learning-v1.json","modes-v1.json"])
        self.assertIn("восстановил 2",report.say())
        for name,original in (("learning-v1.json",original_one),
                              ("modes-v1.json",original_two)):
            self.assertEqual((self.folder/(name+".corrupt-1.bak")).read_bytes(),original)
            self.assertEqual(json.loads((self.folder/name).read_text("utf-8"))["version"],1)
        second=repair_configs(consent=True,folder=self.folder)
        self.assertEqual(second.repaired,())
        self.assertEqual(len(list(self.folder.glob("*.bak"))),2)

    def test_refuse_unknown_future_schema_and_symlinks(self):
        future=self.folder/"modes-v1.json"
        future.write_text(json.dumps({"version":99,"apps":{"x":["hello"]}}),encoding="utf-8")
        self.assertEqual(inspect_configs(self.folder)[1].status,"unsupported")
        report=repair_configs(consent=True,folder=self.folder)
        self.assertIn(future.name,report.manual)
        self.assertEqual(json.loads(future.read_text())["version"],99)
        link=self.folder/"learning-v1.json"
        try:
            link.symlink_to(future)
        except (OSError,NotImplementedError):
            self.skipTest("Symlinks are unavailable on this Windows runner")
        self.assertEqual(inspect_configs(self.folder)[0].status,"unsafe")
        report=repair_configs(consent=True,folder=self.folder)
        self.assertIn(link.name,report.manual)
        self.assertTrue(link.is_symlink())

    def test_oversize_file_gets_backup_instead_of_deletion(self):
        cfg=self.folder/"learning-v1.json"
        data=b"x"*41_000
        cfg.write_bytes(data)
        self.assertEqual(inspect_configs(self.folder)[0].status,"too_large")
        report=repair_configs(consent=True,folder=self.folder)
        self.assertEqual(report.repaired,("learning-v1.json",))
        self.assertEqual((self.folder/"learning-v1.json.corrupt-1.bak").read_bytes(),data)

    def test_extremely_large_or_unknown_settings_are_never_rewritten(self):
        enormous=self.folder/"learning-v1.json"
        enormous.write_bytes(b"Z"*600_000)
        self.assertEqual(inspect_configs(self.folder)[0].status,"unsafe")
        result=repair_configs(consent=True,folder=self.folder)
        self.assertEqual(result.repaired,())
        self.assertEqual(enormous.stat().st_size,600_000)
        self.assertFalse(list(self.folder.glob("*.bak")))

    def test_valid_json_with_shell_alias_cannot_be_falsely_called_healthy(self):
        cfg=self.folder/"learning-v1.json"
        content=json.dumps({"version":1,"aliases":{"игра":"cmd.exe"},"stats":{}},
                           ensure_ascii=False)
        cfg.write_text(content,encoding="utf-8")
        self.assertEqual(inspect_configs(self.folder)[0].status,"unsafe")
        report=repair_configs(consent=True,folder=self.folder)
        self.assertEqual(report.repaired,())
        self.assertIn(cfg.name,report.manual)
        self.assertEqual(cfg.read_text("utf-8"),content)
        self.assertFalse(list(self.folder.glob("*.bak")))

    def test_invalid_mode_overrides_or_future_modes_get_manual_review(self):
        modes=self.folder/"modes-v1.json"
        for value,status in (({"apps":{"gaming":["cmd.exe"]}},"unsafe"),
                             ({"apps":{"study":["Notepad","cmd.exe"]}},"unsafe"),
                             ({"apps":{"gaming":[]}},"unsafe"),
                             ({"apps":{"new_future_mode":["Notepad"]}},"unsupported")):
            with self.subTest(value=value):
                content=json.dumps({"version":1,**value})
                modes.write_text(content,encoding="utf-8")
                self.assertEqual(inspect_configs(self.folder)[1].status,status)
                report=repair_configs(consent=True,folder=self.folder)
                self.assertEqual(report.repaired,())
                self.assertIn(modes.name,report.manual)
                self.assertEqual(modes.read_text("utf-8"),content)
                self.assertFalse(list(self.folder.glob("*.bak")))

    def test_voice_diagnostic_reports_manual_attention_instead_of_no_damage(self):
        from main import Jarvis
        app=type("Stub",(),{})()
        app.reply=mock.Mock()
        with mock.patch("main.inspect_configs",return_value=[
             type("Finding",(),{"status":"unsafe","name":"learning-v1.json"})()]), \
             mock.patch("main.repair_configs") as fixing, \
             mock.patch("main.messagebox.askyesno") as confirm:
            Jarvis.self_repair_now(app)
            fixing.assert_not_called()
            confirm.assert_not_called()
        self.assertIn("ручной",app.reply.call_args.args[0])
        self.assertIn("не изменены",app.reply.call_args.args[0])

    def test_http_permission_errors_are_not_retried(self):
        import urllib.error
        calls=[]
        def server_denied():
            calls.append(1)
            raise urllib.error.HTTPError("https://commons.wikimedia.org/w/api.php",
                                         403,"Forbidden",{},None)
        with self.assertRaises(urllib.error.HTTPError):
            retry_readonly("commons_search",server_denied)
        self.assertEqual(calls,[1])

    def test_readonly_transient_search_can_retry_once(self):
        attempts=[]
        def transient():
            attempts.append("called")
            if len(attempts)==1:
                raise ConnectionResetError("reset")
            return ["safe-public-clip"]
        self.assertEqual(retry_readonly("commons_search",transient),["safe-public-clip"])
        self.assertEqual(len(attempts),2)

    def test_cancel_between_failures_cannot_retry(self):
        flag=threading.Event()
        calls=[]
        def failing():
            calls.append(1)
            flag.set()
            raise TimeoutError("network")
        with self.assertRaisesRegex(RepairError,"отменена"):
            retry_readonly("commons_search",failing,cancel=flag)
        self.assertEqual(len(calls),1)

    def test_nontransient_errors_and_writes_are_never_retried(self):
        def forbidden():
            self.fail("Unapproved callback was executed")
        for action in ("download_media","run_shell","edit_code","publish","install"):
            with self.subTest(action=action),self.assertRaises(PermissionError):
                retry_readonly(action,forbidden)
        calls=[]
        def deny():
            calls.append(1)
            raise PermissionError("Do not access")
        with self.assertRaises(PermissionError):
            retry_readonly("commons_search",deny)
        self.assertEqual(calls,[1])

    def test_retry_bound_never_turns_into_loop(self):
        calls=[]
        def always_bad():
            calls.append(1)
            raise TimeoutError("unavailable")
        with self.assertRaises(TimeoutError):
            retry_readonly("model_health_probe",always_bad)
        self.assertEqual(len(calls),2)

    def test_voice_repair_requires_confirmation_and_preserves_data(self):
        from main import Jarvis
        aliases=[]
        app=type("Stub",(),{})()
        app._closing=False
        app.log=mock.Mock()
        app.self_repair_now=mock.Mock()
        Jarvis.handle_text(app,"джарвис проверь и исправь ошибки")
        app.self_repair_now.assert_called_once_with()
        app.log.assert_called_once()
        with mock.patch("main.inspect_configs",return_value=[
            type("Finding",(),{"status":"corrupt","name":"learning-v1.json"})()]), \
             mock.patch("main.messagebox.askyesno",return_value=False), \
             mock.patch("main.repair_configs") as repairing:
            app.reply=mock.Mock()
            Jarvis.self_repair_now(app)
            repairing.assert_not_called()
            self.assertIn("отменено",app.reply.call_args.args[0])


if __name__=="__main__":
    unittest.main()

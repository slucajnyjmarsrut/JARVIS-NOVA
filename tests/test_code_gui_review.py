# -*- coding: utf-8 -*-
"""The real coding window must open, allow code review and refuse failed writes."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from code_gui import CodeWindow


class CodingWindowSafetyTests(unittest.TestCase):
    def test_missing_vision_model_can_choose_existing_coder_separately(self):
        from types import SimpleNamespace
        from local_coder_models import InstalledCoder
        from code_workspace import WorkspaceError
        from unittest import mock

        view=mock.Mock()
        view._generation_busy=False
        view._target.return_value=Path("C:/safe-test-project")
        view.language.get.return_value="python"
        view.task.get.return_value="Создай функцию сортировки списка"
        view.modify_existing.get.return_value=False
        view.full_project.get.return_value=False
        view.master.engine="bundled"
        view.master._local_model_ready=False
        with mock.patch("code_gui.messagebox.askyesno",return_value=True) as ask, \
             mock.patch("code_gui.threading.Thread") as worker:
            CodeWindow.generate(view)
        ask.assert_called_once()
        self.assertIn("Qwen Coder",ask.call_args.args[0])
        self.assertTrue(view._coder_opt_in)
        worker.assert_called_once()
        self.assertFalse(view._coder_checked)

        view._coder_checked=False
        view._coder_choice=None
        with mock.patch("local_coder_models.best_installed_coder",
                        return_value=InstalledCoder("qwen2.5-coder:7b",7.0,5_000_000_000)
                        ) as discovered, \
             mock.patch("code_gui.request_local_model",
                        return_value="код на Python") as request:
            result=CodeWindow._model_generator(view,"Напиши Python","python")
        self.assertEqual(result,"код на Python")
        discovered.assert_called_once_with(confirmed=True)
        request.assert_called_once_with(
            "Напиши Python","python",endpoint="http://127.0.0.1:11434",
            model="qwen2.5-coder:7b")
        view._coder_choice=None
        view._coder_checked=False
        with mock.patch("local_coder_models.best_installed_coder",
                        side_effect=OSError("not running")):
            with self.assertRaisesRegex(WorkspaceError,"запусти Ollama"):
                CodeWindow._model_generator(view,"Напиши Python","python")

    def test_real_tk_coding_window_and_fail_closed_install(self):
        import tkinter as tk
        try:
            root=tk.Tk()
        except tk.TclError:
            self.skipTest("No graphical Tk display on runner")
        root.withdraw()
        view=None
        try:
            with tempfile.TemporaryDirectory() as directory:
                view=CodeWindow(root,language="python",task="Demo")
                view.folder.set(directory)
                view.update_idletasks()
                self.assertTrue(view.repair_button.winfo_exists())
                self.assertTrue(view.tests_button.winfo_exists())
                view.starter()
                self.assertIsNotNone(view.result)
                self.assertEqual(str(view.repair_button.cget("state")),"normal")
                self.assertEqual(str(view.tests_button.cget("state")),"normal")
                view._last_test_gate_status="failed"
                with mock.patch("code_gui.messagebox.showerror") as alert:
                    view.install()
                    alert.assert_called_once()
                self.assertFalse((Path(directory)/"src").exists())
                self.assertFalse((Path(directory)/"tests").exists())
                view._last_test_gate_status="blocked"
                with mock.patch("code_gui.messagebox.showerror") as alert:
                    view.install()
                    alert.assert_called_once()
                self.assertFalse(any(Path(directory).iterdir()))
        finally:
            if view is not None:
                view.destroy()
            root.destroy()

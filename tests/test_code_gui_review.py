# -*- coding: utf-8 -*-
"""The real coding window must open, allow code review and refuse failed writes."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from code_gui import CodeWindow


class CodingWindowSafetyTests(unittest.TestCase):
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

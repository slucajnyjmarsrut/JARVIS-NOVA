"""Exercise the real Jarvis root constructor without loading AI models.

This catches window positioning or widget wiring bugs that only appear after
main.py wires the compact UI, even when individual UI tests pass.
"""
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import sys
import tkinter as tk


class RealCompactBootTests(TestCase):
    def test_main_constructs_compact_window_then_mini_on_hide(self):
        try:
            import main
            from main import Jarvis
            with ExitStack() as stack:
                for target in (
                    "main.LearningStore","main.ModeManager","main.GameCatalog",
                    "main.Desktop","main.LocalChat"):
                    stack.enter_context(patch(target))
                speaker=stack.enter_context(patch("main.Speaker"))
                speaker.return_value.busy=False
                trimodal=stack.enter_context(patch("main.TrimodalService"))
                trimodal.return_value.speaking=False
                trimodal.return_value.runtime=Mock()
                voice=stack.enter_context(patch("main.RC4Voice"))
                voice.return_value.until=0
                voice.return_value.sensitivity=1.2
                # Do not start the asynchronous microphone or model loaders.
                stack.enter_context(patch("main.threading.Thread"))
                # Always start from default geometry, not a runner's saved state.
                stack.enter_context(patch("main.load_layout",return_value={}))
                app=Jarvis()
                try:
                    app.update_idletasks()
                    app.update()
                    self.assertLessEqual(app.winfo_width(),468)
                    self.assertGreaterEqual(app.winfo_width(),385)
                    self.assertIsNotNone(app.hud_minimize_button)
                    self.assertTrue(app.history.winfo_exists())
                    self.assertTrue(app.overlay.winfo_exists())
                    self.assertEqual(app.overlay.state(),"withdrawn")
                    # Compact layout retains access to microphone sensitivity.
                    with patch("main.simpledialog.askfloat",return_value=1.55):
                        app.adjust_sensitivity()
                    voice.return_value.set_sensitivity.assert_called_with(1.55)
                    self.assertIn("1.55",app.status.get())
                    voice.return_value.set_sensitivity.reset_mock()
                    with patch("main.simpledialog.askfloat",return_value=None):
                        app.adjust_sensitivity()
                    voice.return_value.set_sensitivity.assert_not_called()
                    app.hide_main()
                    app.update()
                    self.assertEqual(app.state(),"withdrawn")
                    self.assertEqual(app.overlay.state(),"normal")
                    self.assertLessEqual(app.overlay.winfo_width(),334)
                    app.show_main()
                    app.update()
                    self.assertEqual(app.state(),"normal")
                    self.assertEqual(app.overlay.state(),"withdrawn")
                finally:
                    app._closing=True
                    if app.overlay.winfo_exists():
                        app.overlay.shutdown()
                    app.destroy()
        except tk.TclError as exc:
            if sys.platform=="win32":
                self.fail("Windows desktop boot failed: "+str(exc))
            self.skipTest("No Tk display: "+str(exc))


if __name__ == "__main__":
    import unittest
    unittest.main()

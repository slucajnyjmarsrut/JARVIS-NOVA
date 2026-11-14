# -*- coding: utf-8 -*-
"""Typed-only exit must stop active tasks without spawning any speech hardware."""
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from text_only_main import TextJarvis


class ShutdownTests(unittest.TestCase):
    def test_close_is_idempotent_and_revokes_session_permissions(self):
        app=SimpleNamespace(
            _closing=False,
            save_window_layout=Mock(),
            _command_palette=SimpleNamespace(close=Mock()),
            _shutdown=threading.Event(),
            _model_download_cancel=threading.Event(),
            _model_scan_cancel=threading.Event(),
            overlay=SimpleNamespace(shutdown=Mock()),
            _viral_window=SimpleNamespace(cancel=Mock()),
            local_chat=SimpleNamespace(close=Mock()),
            freellm_chat=SimpleNamespace(close=Mock()),
            _focus_epoch=1, _focus_deadline=100,
            control_allowed=True,vision_allowed=True,
            runtime=SimpleNamespace(stop=Mock()),
            destroy=Mock(),
        )
        with patch("text_only_main.threading.Thread") as runner:
            TextJarvis.close(app)
            TextJarvis.close(app)
        self.assertTrue(app._closing)
        self.assertTrue(app._shutdown.is_set())
        self.assertTrue(app._model_download_cancel.is_set())
        self.assertTrue(app._model_scan_cancel.is_set())
        self.assertFalse(app.control_allowed)
        self.assertFalse(app.vision_allowed)
        self.assertEqual(app._focus_epoch,2)
        app.local_chat.close.assert_called_once()
        app.freellm_chat.close.assert_called_once()
        app.overlay.shutdown.assert_called_once()
        app._viral_window.cancel.assert_called_once()
        app.destroy.assert_called_once()
        runner.return_value.start.assert_called_once()
        runner.assert_called_once()

    def test_shutdown_does_not_reference_deleted_audio_engine(self):
        import inspect
        source=inspect.getsource(TextJarvis.close)
        for forbidden in ("speaker", "voice_engine", "microphone",
                          "speech", "trimodal", "whisper"):
            self.assertNotIn(forbidden,source)


if __name__=="__main__":
    unittest.main()

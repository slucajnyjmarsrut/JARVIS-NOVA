"""Privacy regression: no webcam capture backend, no camera UI/voice commands."""
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from main import Jarvis
from trimodal_service import TrimodalService
from voice_engine import Voice


ROOT=Path(__file__).resolve().parents[1]


class NoCameraTests(unittest.TestCase):
    def test_no_webcam_module_or_opencv_dependency_is_shipped(self):
        self.assertFalse((ROOT/"camera_capture.py").exists())
        requirements=(ROOT/"requirements-windows.txt").read_text(encoding="utf-8")
        spec=(ROOT/"jarvis_nova.spec").read_text(encoding="utf-8")
        self.assertNotIn("opencv-python",requirements)
        self.assertNotIn("'cv2'",spec)
        self.assertIn("excludes=['cv2'",spec)

    def test_ui_contains_no_camera_buttons_or_menu(self):
        ui=(ROOT/"nova_ui.py").read_text(encoding="utf-8")
        main=(ROOT/"main.py").read_text(encoding="utf-8")
        self.assertNotIn('("КАМЕРА",',ui)
        self.assertNotIn('request_trimodal("camera")',ui+main)
        self.assertNotIn('label="Спросить голосом о камере',main)

    def test_camera_words_never_activate_vision_source(self):
        voice=Voice(lambda _:None,lambda _:None,lambda:False)
        for phrase in ("джарвис посмотри в камеру",
                       "джарвис что перед камерой",
                       "опиши камеру","look at webcam"):
            self.assertIsNone(voice.vision_source(phrase))
        self.assertEqual(voice.vision_source("посмотри на экран"),"screen")

    def test_service_denies_camera_before_initialization(self):
        service=TrimodalService.__new__(TrimodalService)
        with self.assertRaisesRegex(ValueError,"Webcam capture"):
            service.run_once(source="camera",screen_consent=True)

    def test_explicit_camera_request_is_rejected_before_app_launch(self):
        app=SimpleNamespace(_closing=False,log=Mock(),reply=Mock(),
                            show_main=Mock(),hide_main=Mock(),
                            modes=SimpleNamespace(parse=Mock(return_value=None)),
                            desktop=SimpleNamespace(is_installed=Mock()))
        Jarvis.handle_text(app,"Открой камеру")
        app.reply.assert_called_once()
        self.assertIn("удалена",app.reply.call_args.args[0])
        app.desktop.is_installed.assert_not_called()


if __name__=="__main__":
    unittest.main()

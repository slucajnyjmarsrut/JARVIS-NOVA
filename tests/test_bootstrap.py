
import unittest, tempfile, sys, threading, json
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap
from main import Jarvis

class SmokeTests(unittest.TestCase):
    def test_missing_model_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'ollama').mkdir()
            (root/'ollama'/'ollama.exe').write_bytes(b'Ollama')
            (root/'bin').mkdir()
            for tool in ('ffmpeg.exe','ffprobe.exe'):
                (root/'bin'/tool).write_bytes(b'FFmpeg')
            with patch('bootstrap._assets_root',return_value=root):
                self.assertEqual(bootstrap.smoke_test(),5)

    def test_text_only_models_and_python_imports(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'ollama').mkdir()
            (root/'ollama'/'ollama.exe').write_bytes(b'unit-test')
            (root/'bin').mkdir()
            for tool in ('ffmpeg.exe','ffprobe.exe'):
                (root/'bin'/tool).write_bytes(b'test')
            manifest=root/'models/ollama/manifests/registry.ollama.ai/library/qwen3-vl/2b-instruct'
            manifest.parent.mkdir(parents=True)
            digest='sha256:'+'f'*64
            manifest.write_text(json.dumps({'config':{'digest':digest,'size':1},'layers':[]}))
            blob=root/'models/ollama/blobs'/('sha256-'+'f'*64)
            blob.parent.mkdir()
            blob.write_bytes(b'x')
            with patch('bootstrap._assets_root',return_value=root):
                with patch('importlib.util.find_spec',return_value=object()):
                    self.assertEqual(bootstrap.smoke_test(),0)
                    # Presence of ANY legacy voice model must fail closed.
                    (root/'models'/'base.pt').write_bytes(b'old-whisper')
                    self.assertEqual(bootstrap.smoke_test(),7)

    def test_old_agent_cannot_boot_speech(self):
        from main import Jarvis
        import inspect
        source=inspect.getsource(Jarvis)
        for forbidden in ("init_voice", "toggle_voice",
                          "self.speaker", "self.voice", "self.trimodal"):
            self.assertNotIn(forbidden,source)

    def test_current_entrypoint_uses_text_only_application(self):
        import inspect
        self.assertIn("from text_only_main import TextJarvis",
                      inspect.getsource(bootstrap.main))
        self.assertIn("TextJarvis().mainloop()",
                      inspect.getsource(bootstrap.main))


if __name__ == '__main__':
    unittest.main()

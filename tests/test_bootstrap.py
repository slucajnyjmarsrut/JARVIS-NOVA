
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

    def test_voice_starts_before_loading_silero(self):
        events=[]
        fake=type('JarvisStub', (), {})()
        fake._shutdown=threading.Event()
        fake.voice=type('VoiceStub', (), {'start': lambda self:events.append('voice'),
                    'stop':lambda self: events.append('stop')})()
        fake.speaker=type('SpeakerStub', (), {'load':lambda self:events.append('silero') or 'ready'})()
        fake.voice_enabled=False
        fake.q=type('QueueStub', (), {'put':lambda self,x:None})()
        Jarvis.init_voice(fake)
        self.assertEqual(events,['voice','silero'])
        self.assertTrue(fake.voice_enabled)

    def test_shutdown_during_voice_boot(self):
        events=[]
        fake=type('JarvisStub', (), {})()
        fake._shutdown=threading.Event()
        def start():
            events.append('voice')
            fake._shutdown.set()
        fake.voice=type('VoiceStub', (), {'start':lambda self:start(),
                    'stop':lambda self:events.append('stop')})()
        fake.speaker=Mock()
        fake.q=Mock()
        Jarvis.init_voice(fake)
        self.assertEqual(events,['voice','stop'])
        fake.speaker.load.assert_not_called()

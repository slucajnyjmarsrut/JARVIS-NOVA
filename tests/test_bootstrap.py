
import unittest, tempfile, sys, threading, json
from pathlib import Path
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootstrap
from main import Jarvis

class SmokeTests(unittest.TestCase):
    def test_missing_model_fails(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('speaker.assets', return_value=Path(d)):
                self.assertEqual(bootstrap.smoke_test(), 2)

    def test_all_models_and_python_imports(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'models'
            for rel in ['vosk/am/final.mdl','base.pt','v5_ru.pt']:
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes(b'A'*2000)
            (root.parent/'ollama').mkdir()
            (root.parent/'ollama'/'ollama.exe').write_bytes(b'unit-test-placeholder')
            manifest=root/'ollama/manifests/registry.ollama.ai/library/qwen3-vl/2b'
            manifest.parent.mkdir(parents=True)
            digest='sha256:'+'f'*64
            manifest.write_text(json.dumps({'config':{'digest':digest,'size':1},'layers':[]}))
            blob=root/'ollama/blobs'/('sha256-'+'f'*64)
            blob.parent.mkdir()
            blob.write_bytes(b'x')
            with patch('speaker.assets', return_value=root):
                with patch('importlib.util.find_spec', return_value=object()):
                    self.assertEqual(bootstrap.smoke_test(),0)

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

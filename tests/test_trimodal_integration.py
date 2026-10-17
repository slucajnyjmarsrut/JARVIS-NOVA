"""Control-flow tests: these are NOT tests of real model inference."""
from __future__ import annotations
import json
import hashlib
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

import numpy as np
from PIL import Image

from bundled_vision_runtime import (BundledVisionRuntime, BundledRuntimeConfig,
                                    BundledRuntimeError, validate_offline_model_store)
from screen_capture import ScreenFrameSource
from trimodal_pipeline import TriModalPipeline, PipelineError
from trimodal_service import TrimodalService
from voice_engine import Voice

JPEG = b'\xff\xd8\xff' + b'x' * 50 + b'\xff\xd9'


class TrimodalPipelineTests(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.rec=Mock(ready=True)
        self.rec.transcribe.side_effect=lambda x, sample_rate: self.events.append('whisper') or 'Какого цвета квадрат?'
        self.vision=Mock(ready=True)
        self.vision.describe.side_effect=lambda text,jpg: self.events.append('vision') or 'Красный.'
        self.silero=Mock(ready=True)
        self.silero.play.side_effect=lambda text: self.events.append('silero')
        self.mic=Mock(side_effect=lambda seconds: self.events.append('mic') or np.ones(16_000,dtype=np.float32))
        self.camera=Mock()
        self.camera.capture_jpeg.side_effect=lambda: self.events.append('camera') or JPEG
        self.screen=Mock()
        self.screen.capture_jpeg.side_effect=lambda: self.events.append('screen') or JPEG
        self.pipeline=TriModalPipeline(recognizer=self.rec,vision=self.vision,synthesizer=self.silero,
                                       microphone=self.mic,camera=self.camera,screen=self.screen)

    def test_screen_no_permission_no_access(self):
        with self.assertRaises(PermissionError):
            self.pipeline.run_once(source='screen',screen_consent=False)
        self.rec.transcribe.assert_not_called()
        self.screen.capture_jpeg.assert_not_called()

    def test_same_vosk_pcm_whisper_vision_silero_screen(self):
        samples=np.ones(16000,dtype=np.float32)
        result=self.pipeline.run_once(source='screen',screen_consent=True,audio_samples=samples)
        self.assertEqual(result.source,'screen')
        self.assertFalse(result.camera_used)
        self.assertEqual(self.events,['whisper','screen','vision','silero'])
        self.camera.capture_jpeg.assert_not_called()
        self.mic.assert_not_called()

    def test_camera_microphone_whisper_vision_silero(self):
        result=self.pipeline.run_once(source='camera',camera_consent=True)
        self.assertTrue(result.camera_used)
        self.assertEqual(self.events,['mic','whisper','camera','vision','silero'])

    def test_reject_same_time_without_access(self):
        self.pipeline._guard.acquire()
        try:
            with self.assertRaisesRegex(PipelineError,'still running'):
                self.pipeline.run_once(source='screen',screen_consent=True)
        finally:self.pipeline._guard.release()
        self.mic.assert_not_called()

    def test_unknown_image_source(self):
        with self.assertRaises(ValueError):
            self.pipeline.run_once(source='url',screen_consent=True)

    def test_speech_silence_does_not_capture(self):
        self.rec.transcribe.side_effect=lambda *a,**k:'   '
        result=self.pipeline.run_once(source='screen',screen_consent=True)
        self.assertFalse(result.answer)
        self.screen.capture_jpeg.assert_not_called()
        self.vision.describe.assert_not_called()

    def test_no_fake_answer_on_inference_error(self):
        self.vision.describe.side_effect=ValueError('missing vision')
        with self.assertRaisesRegex(PipelineError,'missing vision'):
            self.pipeline.run_once(source='screen',screen_consent=True)
        self.silero.play.assert_not_called()


class ScreenTests(unittest.TestCase):
    def test_real_pillow_encodes_synthetic_image_in_memory(self):
        image=Image.new('RGB',(2000,1500),'red')
        jpeg=ScreenFrameSource(grab=lambda:image).capture_jpeg()
        self.assertGreater(len(jpeg),100)
        self.assertTrue(jpeg.startswith(b'\xff\xd8\xff'))
        self.assertEqual(image.size,(2000,1500))


class BundledStoreTests(unittest.TestCase):
    def test_missing_model_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(BundledRuntimeError,'Missing offline Vision'):
                validate_offline_model_store(Path(td))

    def test_manifest_blobs_checked(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            base=root/'models/ollama'
            manifest=base/'manifests/registry.ollama.ai/library/qwen3-vl/2b'
            manifest.parent.mkdir(parents=True)
            digest='sha256:'+'a'*64
            manifest.write_text(json.dumps({'config':{'digest':digest,'size':2},'layers':[]}))
            blob=base/'blobs'/('sha256-'+'a'*64)
            blob.parent.mkdir()
            blob.write_bytes(b'aa')
            validate_offline_model_store(root)
            with self.assertRaisesRegex(BundledRuntimeError,'SHA256 mismatch'):
                validate_offline_model_store(root, verify_hashes=True)
            correct = hashlib.sha256(b'aa').hexdigest()
            manifest.write_text(json.dumps({'config': {'digest': 'sha256:'+correct, 'size':2},'layers':[]}))
            (blob.parent/('sha256-'+correct)).write_bytes(b'aa')
            validate_offline_model_store(root, verify_hashes=True)
            (blob.parent/('sha256-'+correct)).write_bytes(b'b')
            with self.assertRaisesRegex(BundledRuntimeError,'size mismatch'):
                validate_offline_model_store(root)

    def test_bundle_runtime_never_runs_on_linux(self):
        import os
        if os.name=='nt':self.skipTest('Windows-only check')
        with tempfile.TemporaryDirectory() as td:
            p=BundledVisionRuntime(BundledRuntimeConfig(Path(td)))
            with self.assertRaisesRegex(BundledRuntimeError,'requires Windows'):
                p.start()


class VoiceIntegrationTests(unittest.TestCase):
    def test_vision_source_cannot_imply_consent(self):
        v=Voice(lambda _:None,lambda _:None,lambda:False)
        self.assertEqual(v.vision_source('Джарвис, что ты видишь?'),'screen')
        self.assertEqual(v.vision_source('Джарвис, что перед камерой?'),'camera')
        self.assertIsNone(v.vision_source('Джарвис, открой Chrome'))


if __name__ == '__main__': unittest.main()

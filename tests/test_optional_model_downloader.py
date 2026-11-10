# -*- coding: utf-8 -*-
"""Lite Qwen download stall reporting, safe cancellation, and partial retention."""
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
import queue
import tempfile
import threading
import unittest
from unittest import mock

from optional_model_downloader import (
    ModelDownloadError, downloaded_blob_bytes, wait_for_pull,
    pull_model_with_retries, required_free_bytes, model_download_lock,
    _pull_error_hint, _NoRedirect,
)


class FakeTime:
    def __init__(self):
        self.value=100.0

    def monotonic(self):
        return self.value

    def sleep(self,seconds):
        self.value+=seconds


class PullProcess:
    def __init__(self, clock, *, stop_at=None, code=0):
        self.clock=clock
        self.stop_at=stop_at
        self.code=code

    def poll(self):
        return self.code if self.stop_at is not None and self.clock.value>=self.stop_at else None


class ModelDownloadStallTests(unittest.TestCase):
    def test_lite_reports_stalled_partial_and_keeps_existing_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)
            blobs=folder/"blobs"
            blobs.mkdir()
            partial=blobs/"sha256-something-partial"
            partial.write_bytes(b"partial data for retry")
            initial=partial.read_bytes()
            clock=FakeTime()
            sizes=[]
            with self.assertRaisesRegex(ModelDownloadError,"остановилась"):
                wait_for_pull(PullProcess(clock),folder,threading.Event(),
                              progress=sizes.append,
                              clock=clock.monotonic,sleep=clock.sleep,
                              max_wait=100,stall_wait=1.4)
            self.assertEqual(partial.read_bytes(),initial)
            self.assertTrue(sizes)
            self.assertTrue(all(size==len(initial) for size in sizes))

    def test_successful_download_after_short_pauses_does_not_timeout(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)
            blobs=folder/"blobs"
            blobs.mkdir()
            partial=blobs/"sha256-something-partial"
            partial.write_bytes(b"first chunk")
            clock=FakeTime()
            original_sleep=clock.sleep

            def advance(seconds):
                original_sleep(seconds)
                if 101.0<=clock.value<=101.3 and partial.stat().st_size<100:
                    partial.write_bytes(b"x"*100)

            wait_for_pull(PullProcess(clock,stop_at=102.0),
                          folder,threading.Event(),clock=clock.monotonic,
                          sleep=advance,max_wait=10,stall_wait=1.5)
            self.assertEqual(partial.stat().st_size,100)

    def test_cancel_keeps_partial_and_does_not_need_network(self):
        with tempfile.TemporaryDirectory() as root:
            store=Path(root)
            blobs=store/"blobs"
            blobs.mkdir()
            file=blobs/"partial"
            file.write_bytes(b"already downloaded")
            cancel=threading.Event()
            cancel.set()
            with self.assertRaisesRegex(ModelDownloadError,"отменена"):
                wait_for_pull(PullProcess(FakeTime()),store,cancel)
            self.assertEqual(file.read_bytes(),b"already downloaded")

    def test_nonzero_ollama_exit_is_explained_not_reported_as_ready(self):
        with tempfile.TemporaryDirectory() as root:
            clock=FakeTime()
            with self.assertRaisesRegex(ModelDownloadError,"Ollama не скачала"):
                wait_for_pull(PullProcess(clock,stop_at=100.0,code=7),
                              Path(root),threading.Event(),
                              clock=clock.monotonic,sleep=clock.sleep)

    def test_max_duration_terminates_even_if_disk_reports_changing(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)
            clock=FakeTime()
            with mock.patch("optional_model_downloader.downloaded_blob_bytes",
                            side_effect=range(100)):
                with self.assertRaisesRegex(ModelDownloadError,"общий предел"):
                    wait_for_pull(PullProcess(clock),folder,threading.Event(),
                                  clock=clock.monotonic,sleep=clock.sleep,
                                  max_wait=1,stall_wait=10)

    @staticmethod
    def mock_pull_retries(folder, codes, *, failure_text=b"proxy connection reset", waiter=None):
        """No network, no Ollama installation or model weights required."""
        class FakePull:
            def __init__(self,code):
                self.exit_code=code
                self.stdout=BytesIO(failure_text)
                self.terminated=False

            def poll(self):
                return self.exit_code

            def terminate(self):
                self.terminated=True
                self.exit_code=-15

            def wait(self,timeout=None):
                return self.exit_code

            def kill(self):
                self.terminate()

        attempts=[]
        commands=[]
        stage=[]
        def runner(command, **kwargs):
            commands.append(command)
            item=FakePull(codes[len(attempts)])
            attempts.append(item)
            return item
        def check(pull,store,cancel,progress=None):
            if waiter is not None:
                return waiter(pull,store,cancel,progress)
            if pull.poll()!=0:
                raise ModelDownloadError("Ollama не скачала модель")
        with mock.patch("optional_model_downloader.shutil.disk_usage",
                        return_value=SimpleNamespace(free=10_000_000_000)):
            pull_model_with_retries(
                Path(folder)/"ollama.exe",Path(folder),threading.Event(),
                runner=runner,server=SimpleNamespace(poll=lambda:None),
                env={"OLLAMA_NO_CLOUD":"1"},stage=stage.append,
                waiter=check,pause=lambda seconds:False)
        return attempts,commands,stage

    def test_retry_two_failed_attempts_and_success_without_losing_cache(self):
        with tempfile.TemporaryDirectory() as root:
            store=Path(root)
            blobs=store/"blobs"
            blobs.mkdir()
            partial=blobs/"sha256-chunk-partial"
            partial.write_bytes(b"previously downloaded chunk")
            before=partial.read_bytes()
            processes,commands,messages=self.mock_pull_retries(store,[1,1,0])
            self.assertEqual(len(processes),3)
            self.assertTrue(all(cmd[1:] == ["pull","qwen3-vl:2b-instruct"]
                                for cmd in commands))
            self.assertIn("попытка 3 из 3"," ".join(messages))
            self.assertIn("прокси"," ".join(messages))
            self.assertEqual(partial.read_bytes(),before)

    def test_stall_kills_old_pull_before_retrying_and_cancel_aborts(self):
        with tempfile.TemporaryDirectory() as root:
            store=Path(root)
            store.joinpath("blobs").mkdir()
            calls=0
            def crash(pull, *_):
                nonlocal calls
                calls+=1
                if calls==1:
                    self.assertIsNone(pull.poll())
                    raise ModelDownloadError("Загрузка Qwen остановилась")
                self.assertEqual(calls,2)
            processes,_,_=self.mock_pull_retries(
                store,[None,0],waiter=crash)
            self.assertTrue(processes[0].terminated)
            self.assertFalse(processes[1].terminated)

    def test_exhausted_retries_keep_partial_and_sanitize_errors(self):
        with tempfile.TemporaryDirectory() as root:
            store=Path(root)
            directory=store/"blobs"
            directory.mkdir()
            file=directory/"partial"
            file.write_bytes(b"safe model bytes")
            with self.assertRaisesRegex(ModelDownloadError,"после 3 попыток"):
                self.mock_pull_retries(store,[1,1,1],
                    failure_text=b"proxy connection broken at C:/private/folder")
            self.assertEqual(file.read_bytes(),b"safe model bytes")
            self.assertNotIn("C:/private",_pull_error_hint(
                b"proxy connection broken at C:/private/folder"))

    def test_concurrent_download_is_blocked_but_lock_auto_releases(self):
        with tempfile.TemporaryDirectory() as root:
            store=Path(root)
            blob=store/"blobs"/"partial"
            blob.parent.mkdir()
            blob.write_bytes(b"previous download")
            with model_download_lock(store):
                with self.assertRaisesRegex(ModelDownloadError,"уже скачивается"):
                    with model_download_lock(store):
                        self.fail("concurrent model download lock was bypassed")
                self.assertEqual(blob.read_bytes(),b"previous download")
            # After the first process releases its OS lock, retry is possible.
            with model_download_lock(store):
                self.assertEqual(blob.read_bytes(),b"previous download")
            self.assertTrue((store/".jarvis-qwen-download.lock").is_file())

    def test_diagnostics_report_disk_and_tls_without_exposing_logs(self):
        self.assertIn("места",_pull_error_hint(
            b"no space left on device at C:/user/private"))
        self.assertIn("TLS",_pull_error_hint(
            b"x509: certificate signed by unknown authority"))
        self.assertNotIn("C:/user",_pull_error_hint(
            b"proxy connection reset at C:/user/private"))

    def test_resume_disk_space_does_not_need_three_gb_again(self):
        self.assertEqual(required_free_bytes(0),3_000_000_000)
        self.assertEqual(required_free_bytes(1_110_000_000),1_890_000_000)
        self.assertEqual(required_free_bytes(3_000_000_000),800_000_000)

    def test_downloader_tags_reject_external_redirects(self):
        import urllib.request
        handler=_NoRedirect()
        with self.assertRaises(ModelDownloadError):
            handler.redirect_request(None,None,302,"Found",{},
                                     "https://evil.example/collect")
        captured=[]
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*a):return None
            def read(self,limit):return b'{"models":[]}'
        class Opener:
            def open(self,url,timeout):return Reply()
        with mock.patch.object(urllib.request,"build_opener",
                 side_effect=lambda *args:(captured.extend(args),Opener())[1]):
            from optional_model_downloader import _loopback_tags
            _loopback_tags("http://127.0.0.1:12345")
        self.assertTrue(any(isinstance(h,_NoRedirect) for h in captured))

    def test_ui_exposes_cancel_only_during_download(self):
        from nova_command_palette import entries
        app=mock.Mock()
        app._model_download_busy=False
        labels=[r[1] for r in entries(app) if r]
        self.assertNotIn("Отменить загрузку Qwen",labels)
        app._model_download_busy=True
        rows=[r for r in entries(app) if r]
        cancel=next(r for r in rows if r[1]=="Отменить загрузку Qwen")
        self.assertEqual(cancel[2],app.cancel_local_model_download)
        from text_only_main import TextJarvis
        app._model_download_cancel=threading.Event()
        TextJarvis.cancel_local_model_download(app)
        self.assertTrue(app._model_download_cancel.is_set())

    def test_ui_warns_after_a_minute_without_new_bytes(self):
        from text_only_main import TextJarvis
        app=mock.Mock()
        app._closing=False
        app._model_download_cancel=threading.Event()
        app._model_download_last_size=1_110_000_000
        app._model_download_last_change=100.0
        app._model_download_queue=queue.Queue()
        app._model_download_queue.put(("progress",1_110_000_000))
        with mock.patch("text_only_main.time.monotonic",return_value=195.0):
            TextJarvis._pump_model_download(app)
        self.assertIn("нет новых данных",app.status.set.call_args.args[0])
        self.assertIn("1.11 ГБ",app.status.set.call_args.args[0])
        app.after.assert_called_once()


if __name__=="__main__":
    unittest.main()

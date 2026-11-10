# -*- coding: utf-8 -*-
"""Lite Qwen download stall reporting, safe cancellation, and partial retention."""
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest import mock

from optional_model_downloader import (
    ModelDownloadError, downloaded_blob_bytes, wait_for_pull,
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

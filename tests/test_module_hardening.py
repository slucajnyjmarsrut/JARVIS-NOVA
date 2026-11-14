# -*- coding: utf-8 -*-
"""Cross-component hardening: durable watcher, bounded local protocol and disk safety.

All scenarios are offline; no models started, images captured, external files
touched, shell commands or network requests issued.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
from unittest import TestCase, mock
import unittest

from local_chat import LocalChat, LocalChatError
from night_resource_guard import MIB, MemorySnapshot
from night_supervisor import NightSupervisor
from night_supervisor_service import run_forever
from quick_video_brief import quick_brief
from topic_video_engine import (
    MIN_VIDEO_FREE_BYTES, TopicVideoError, render_topic_video,
)


class HardeningTests(TestCase):
    def test_watchdog_recovers_from_unexpected_model_adapter_exception(self):
        stop = Event()
        invocations = []
        class FlakyAdapter:
            def background_enabled(self):
                return True
            def background_run_next(self, *, cancel):
                invocations.append(True)
                if len(invocations) == 1:
                    raise KeyError("C:/Users/private/secret")
                return False
        adapter = FlakyAdapter()
        factories = []
        def factory(root):
            factories.append(root)
            return adapter
        waits = []
        def await_next(seconds):
            waits.append(seconds)
            if len(waits) == 2:
                stop.set()
        with mock.patch.object(stop, "wait", side_effect=await_next), \
                mock.patch("night_supervisor_service._LOG") as logger:
            run_forever("only-this-local-queue", supervisor_factory=factory,
                        stop_event=stop, poll_seconds=3)
            self.assertEqual(len(invocations), 2)
            self.assertEqual(len(factories), 2)
            self.assertEqual(waits, [3, 3])
            self.assertEqual(logger.warning.call_count, 1)
            self.assertIn("KeyError", logger.warning.call_args.args)
            self.assertNotIn("secret", str(logger.warning.call_args))

    def test_corrupt_ram_metrics_defer_approved_task(self):
        with TemporaryDirectory() as temp:
            calls = []
            def invalid_memory():
                raise TypeError("invalid vendor status")
            def executor(job, progress):
                calls.append(job.id)
                raise AssertionError("Must not execute with unknown RAM")
            s = NightSupervisor(
                Path(temp)/"queue", executor=executor,
                memory_probe=invalid_memory, resource_release=lambda: 0)
            s.enqueue("scenario", "Make Minecraft video",
                      approved=True, allow_new_files=True)
            self.assertFalse(s.background_run_next())
            self.assertEqual(calls, [])
            self.assertEqual(s.list_jobs()[0].status, "waiting_memory")

    def test_unload_import_failure_cannot_kill_queue(self):
        from dataclasses import asdict, replace
        from quick_video_brief import quick_brief
        with TemporaryDirectory() as temp:
            def scenario(job, progress):
                return {"brief":asdict(replace(
                    quick_brief("minecraft"),generator="локальная Gemma3:4b")),
                    "model":"gemma3:4b"}
            def unload():
                raise ImportError("Ollama local registry temporarily unavailable")
            s = NightSupervisor(
                Path(temp)/"queue", executor=scenario,
                memory_probe=lambda:MemorySnapshot(4000*MIB,8000*MIB),
                resource_release=unload)
            s.enqueue("scenario", "Make Minecraft video",
                      approved=True, allow_new_files=True)
            self.assertTrue(s.background_run_next())
            self.assertEqual(s.list_jobs()[0].status, "completed")
            self.assertIn("memory_release_unavailable",
                          [entry[3] for entry in s.journal()])

    def test_mp4_never_starts_when_output_volume_lacks_space(self):
        with TemporaryDirectory() as temp:
            root=Path(temp)
            source=quick_brief("Minecraft")
            for amount in (None, -1, True, MIN_VIDEO_FREE_BYTES-1):
                with self.subTest(free=amount):
                    calls=[]
                    def executor(*args, **kwargs):
                        calls.append(args)
                        raise AssertionError("FFmpeg must not execute")
                    with self.assertRaises(TopicVideoError):
                        render_topic_video(
                            source, root,
                            tools=("ffmpeg","ffprobe"),
                            executor=executor,
                            disk_probe=lambda path: amount)
                    self.assertEqual(calls, [])
                    self.assertEqual(list(root.iterdir()), [])

    def test_mp4_disk_probe_error_fails_closed_without_path_leak(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)
            def failed_probe(_):
                raise OSError("D:/Private/username/sensitive")
            with self.assertRaises(TopicVideoError) as caught:
                render_topic_video(
                    quick_brief("Minecraft"),path,tools=("ffmpeg","ffprobe"),
                    disk_probe=failed_probe)
            self.assertNotIn("sensitive", str(caught.exception))
            self.assertEqual(list(path.iterdir()), [])

    def test_coder_large_project_context_includes_last_modules(self):
        from code_project_engine import _context
        sources={f"mod_{i:03}.py": "long-source-" * 300
                 for i in range(72)}
        result=_context(sources,max_chars=4900)
        self.assertLessEqual(len(result),4900)
        self.assertIn("FILE mod_000.py",result)
        self.assertIn("FILE mod_071.py",result)
        self.assertEqual(result.count("END FILE"),72)

    def test_coder_small_project_preserves_actual_code(self):
        from code_project_engine import _context
        result=_context({"src/a.py":"def add(a,b): return a+b",
                         "src/b.py":"from src.a import add"})
        self.assertIn("def add(a,b): return a+b",result)
        self.assertIn("from src.a import add",result)

    def test_coder_context_rejects_impossible_budget(self):
        from code_project_engine import _context
        from code_workspace import WorkspaceError
        for bad in (0, -1, True, 20001, 40.5, None):
            with self.subTest(value=bad), self.assertRaises(WorkspaceError):
                _context({"a.py":"x"},max_chars=bad)

    def test_local_chat_rejects_bad_url_ports_as_controlled_error(self):
        for endpoint in (
            "http://127.0.0.1:invalid",
            "http://127.0.0.1:99999",
            "http://127.0.0.1:-22",
            "http://127.0.0.1:11434@evil.example",
            "http://[::1:11434",
        ):
            with self.subTest(url=endpoint), self.assertRaises(LocalChatError):
                LocalChat._request(endpoint, {"messages":[]})

    def test_malformed_local_model_json_is_never_a_success(self):
        class Reply:
            def __init__(self, payload):
                self.payload=payload
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return None
            def read(self, amount):
                return self.payload
        for body in (b"[]", b"null", b'{"message":null}',
                     b'{"message":[]}', b'{"message":"bad"}'):
            with self.subTest(body=body):
                opener=mock.Mock()
                opener.open.return_value=Reply(body)
                with mock.patch("local_chat.urllib.request.build_opener",
                                return_value=opener):
                    with self.assertRaises(LocalChatError):
                        LocalChat._request(
                            "http://127.0.0.1:11434", {"messages":[]})


if __name__ == "__main__":
    unittest.main()

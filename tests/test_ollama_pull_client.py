# -*- coding: utf-8 -*-
"""The Qwen progress source must be Ollama's streaming API, not blob size."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import urllib.request

from ollama_pull_client import (
    PullAPIError, ProgressLedger, _local_endpoint, _request, _NoRedirect,
    _one_pull, pull_via_api,
)


def frame(status, *, digest=None, completed=None, total=None, error=None):
    result = {"status": status}
    if digest is not None:
        result["digest"] = digest
    if completed is not None:
        result["completed"] = completed
    if total is not None:
        result["total"] = total
    if error is not None:
        result["error"] = error
    return (json.dumps(result) + "\n").encode()


class FakeResponse:
    status = 200

    def __init__(self, frames):
        self.frames = iter(frames)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def readline(self, size):
        return next(self.frames, b"")


class FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        return self.responses.pop(0)


class OllamaStreamTests(unittest.TestCase):
    def test_exact_loopback_only_and_request_never_insecure(self):
        self.assertEqual(_local_endpoint("http://127.0.0.1:19499"),
                         "http://127.0.0.1:19499")
        for bad in (
            "http://127.0.0.1.evil.test:19499",
            "http://localhost:19499",
            "https://127.0.0.1:19499",
            "http://127.0.0.1:19499/other",
            "http://127.0.0.1:19499/?next=external",
            "http://@127.0.0.1:19499",
            "http://name:pass@127.0.0.1:19499",
            "http://127.0.0.1:0",
            "http://127.0.0.1:99999",
            "http://127.0.0.1",
        ):
            with self.subTest(endpoint=bad), self.assertRaises(PullAPIError):
                _local_endpoint(bad)
        req = _request("http://127.0.0.1:19499")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.full_url, "http://127.0.0.1:19499/api/pull")
        self.assertEqual(json.loads(req.data),
                         {"model": "qwen3-vl:2b-instruct",
                          "stream": True, "insecure": False})

    def test_real_server_byte_counters_override_preallocated_blob_sizes(self):
        with tempfile.TemporaryDirectory() as root:
            # A preallocated file may be far larger than actual bytes.
            # Keep test disk usage small; the discrepancy is what matters.
            path = Path(root) / "blobs" / "sha256-preallocated-partial"
            path.parent.mkdir()
            with path.open("wb") as f:
                f.truncate(1_110_000)
            progress = []
            stages = []
            ledger = ProgressLedger()
            self.assertFalse(ledger.update(
                {"status": "pulling abc", "digest": "sha256:abc",
                 "total": 1_900_000_000, "completed": 17_000},
                progress=progress.append, stage=stages.append))
            ledger.update(
                {"status": "pulling abc", "digest": "sha256:abc",
                 "total": 1_900_000_000, "completed": 200_000},
                progress=progress.append, stage=stages.append)
            self.assertEqual(progress, [17_000, 200_000])
            self.assertNotIn(1_110_000_000, progress)

    def test_multiple_digests_monotonic_and_stage_transitions(self):
        ledger = ProgressLedger()
        updates, stages = [], []
        events = [
            {"status": "pulling manifest"},
            {"status": "pulling a", "digest": "sha256:a", "total": 100, "completed": 25},
            {"status": "pulling a", "digest": "sha256:a", "total": 100, "completed": 25},
            {"status": "pulling a", "digest": "sha256:a", "total": 100, "completed": 100},
            {"status": "pulling b", "digest": "sha256:b", "total": 50, "completed": 20},
            {"status": "pulling b", "digest": "sha256:b", "total": 50, "completed": 10},
            {"status": "verifying sha256 digest"},
            {"status": "writing manifest"},
            {"status": "success"},
        ]
        self.assertEqual(
            [ledger.update(e, progress=updates.append, stage=stages.append)
             for e in events][-1], True)
        self.assertEqual(updates, [25, 100, 120])
        self.assertEqual(ledger.last_bytes, 120)
        self.assertTrue(any("суммы" in message for message in stages))
        self.assertTrue(any("манифест" in message for message in stages))

    def test_interrupted_stream_retries_and_must_see_success(self):
        opener = FakeOpener(
            FakeResponse([
                frame("pulling manifest"),
                frame("pulling abc", digest="sha256:a", completed=200, total=400),
                # Server closes without success, never considered complete.
            ]),
            FakeResponse([
                frame("pulling abc", digest="sha256:a", completed=400, total=400),
                frame("verifying sha256 digest"),
                frame("writing manifest"),
                frame("success"),
            ]))
        updates, stages = [], []
        bytes_received = pull_via_api(
            "http://127.0.0.1:19123", threading.Event(),
            opener=opener, progress=updates.append, stage=stages.append,
            pause=lambda seconds: False)
        self.assertEqual(bytes_received, 400)
        self.assertEqual(updates, [200, 400])
        self.assertEqual(len(opener.calls), 2)
        self.assertTrue(any("Повторяю" in msg for msg in stages))
        self.assertTrue(all(
            req.full_url == "http://127.0.0.1:19123/api/pull"
            for req, _ in opener.calls))

    def test_stream_end_without_success_always_fails_closed(self):
        opener = FakeOpener(FakeResponse([
            frame("pulling", digest="sha256:a", completed=200, total=500)]))
        with self.assertRaisesRegex(PullAPIError, "без подтверждения"):
            pull_via_api("http://127.0.0.1:19123", threading.Event(),
                         opener=opener, attempts=1)
        self.assertEqual(len(opener.calls), 1)

    def test_fake_successful_file_size_does_not_override_invalid_stream(self):
        ledger = ProgressLedger()
        for event in (
            {"status": "pulling", "digest": "a", "completed": -1},
            {"status": "pulling", "digest": "a", "completed": True},
            {"status": "pulling", "digest": "a", "completed": 999, "total": 200},
            {"status": "pulling", "digest": "../../file", "completed": 100},
            {"status": "pulling", "digest": "a", "completed": 100,
             "total": 100_000_000_000},
            {"status": 2},
        ):
            with self.subTest(event=event), self.assertRaises(PullAPIError):
                ledger.update(event)

    def test_error_fields_never_expose_local_paths_or_secrets(self):
        result = FakeOpener(FakeResponse([
            frame("pulling", error="proxy connection reset at C:/Users/secret/token")]))
        with self.assertRaises(PullAPIError) as caught:
            pull_via_api("http://127.0.0.1:19123", threading.Event(),
                         opener=result, attempts=1)
        self.assertNotIn("C:/Users", str(caught.exception))
        self.assertIn("сети", str(caught.exception))

    def test_explicit_cancel_stops_new_attempts(self):
        event = threading.Event()
        progress = []
        def cancel_on_update(value):
            progress.append(value)
            event.set()
        result = FakeOpener(FakeResponse([
            frame("pulling", digest="a", completed=20, total=30),
            frame("success")]))
        with self.assertRaisesRegex(PullAPIError, "отменена"):
            pull_via_api("http://127.0.0.1:19123", event, opener=result,
                         progress=cancel_on_update)
        self.assertEqual(progress, [20])
        self.assertEqual(len(result.calls), 1)

    def test_malformed_stream_never_marks_model_ready(self):
        result = FakeOpener(FakeResponse([b'{"completed":\n']))
        with self.assertRaisesRegex(PullAPIError, "Некорректный поток"):
            pull_via_api("http://127.0.0.1:19123", threading.Event(),
                         opener=result, attempts=1)

    def test_default_transport_disables_proxies_and_redirects(self):
        recorded = []
        result = FakeOpener(FakeResponse([frame("success")]))
        def builder(*handlers):
            recorded.extend(handlers)
            return result
        with mock.patch.object(urllib.request, "build_opener", side_effect=builder):
            pull_via_api("http://127.0.0.1:19123", threading.Event())
        self.assertTrue(any(isinstance(h, _NoRedirect) for h in recorded))
        self.assertTrue(any(isinstance(h, urllib.request.ProxyHandler)
                            and not h.proxies for h in recorded))


if __name__ == "__main__":
    unittest.main()

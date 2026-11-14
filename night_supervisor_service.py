# -*- coding: utf-8 -*-
"""Unattended JARVIS NOVA Supervisor: local, silent, always-on queue watcher.

Runs in a separate user-level process from the packaged UI, or a daemon
thread during source development. The ONLY job origin is the existing,
explicitly approved SQLite queue. No prompt self-generation, screen capture,
file deletion, model download, network discovery, OS command or publishing.
"""
from __future__ import annotations

import logging
import threading

from night_supervisor import NightSupervisor, SupervisorError

POLL_SECONDS = 15
_LOG = logging.getLogger(__name__)


def run_forever(root=None, *, supervisor_factory=NightSupervisor,
                stop_event=None, poll_seconds=POLL_SECONDS):
    """Monitor and execute already approved queued tasks without Start button.

    Fail closed on resource/DB errors, retry boundedly, and never escalate.
    With stop_event supplied, tests can stop the loop deterministically.
    """
    if type(poll_seconds) not in (int, float) or not 1 <= poll_seconds <= 120:
        raise ValueError("Некорректная частота проверки Supervisor.")
    if stop_event is None:
        stop_event = threading.Event()
    supervisor = None
    while not stop_event.is_set():
        try:
            if supervisor is None:
                supervisor = supervisor_factory(root)
            if supervisor.background_enabled():
                supervisor.background_run_next(cancel=stop_event)
        except Exception as exc:
            # A buggy model adapter, corrupt checkpoint or temporary drive
            # failure must not kill the always-on watchdog permanently.
            # Do not catch BaseException (SystemExit, KeyboardInterrupt).
            # Log the exception *class*, never potentially private paths,
            # prompts, access tokens or arbitrary model output.
            _LOG.warning("Supervisor watcher deferred: %s", type(exc).__name__)
            supervisor = None
        stop_event.wait(poll_seconds)

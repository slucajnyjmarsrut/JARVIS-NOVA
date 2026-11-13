# -*- coding: utf-8 -*-
"""Launch always-on current-user Supervisor; retain legacy night recovery.

Windows packaged builds launch a separate headless process. GUI closing does
not stop that process. Source checkouts use one nonblocking daemon thread.
Login launch is a visible installer Startup option, not hidden persistence.
Only individually approved jobs can run.
"""
from __future__ import annotations

import logging
from pathlib import Path
import os
import subprocess
import sys
import threading

from night_supervisor import NightSupervisor, SupervisorError

_active = None
_lock = threading.Lock()


def start_if_approved(root=None, *, supervisor_factory=NightSupervisor):
    """Start a daemon only when an existing queue database is present.

    The worker itself re-validates durable consent and the original absolute
    deadline. This function does NOT grant permissions or start new jobs
    merely because screen/desktop defaults happen to be enabled.
    """
    global _active
    base = Path(root if root is not None else
                Path.home() / "JARVIS-NOVA-Projects" /
                "Night-Supervisor").absolute()
    if not (base / "night_jobs.sqlite3").is_file():
        return None
    with _lock:
        if _active is not None and _active.is_alive():
            return _active

        def resume():
            try:
                supervisor = supervisor_factory(base)
                if supervisor.run_is_approved():
                    supervisor.run_approved_overnight()
            except (SupervisorError, OSError, ValueError) as exc:
                logging.getLogger(__name__).warning(
                    "Overnight recovery blocked safely: %s", exc)

        _active = threading.Thread(
            target=resume, name="jarvis-approved-night-recovery",
            daemon=True)
        _active.start()
        return _active


_service_thread = None
_spawned = False


def start_always_on(root=None, *, supervisor_factory=NightSupervisor,
                    stop_event=None, popen=None):
    """Start worker without pressing Start; never grant new job permission."""
    global _service_thread, _spawned
    packaged = (
        root is None and supervisor_factory is NightSupervisor and
        stop_event is None and getattr(sys, "frozen", False) and os.name == "nt"
    )
    with _lock:
        if packaged:
            if _spawned:
                return None
            # Frozen JARVIS accepts exactly the headless daemon flag. No
            # shell, no inherited handles, no network or arbitrary argument.
            opener = popen or subprocess.Popen
            try:
                opener(
                    [sys.executable, "--supervisor-daemon"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, close_fds=True,
                    creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) |
                                   getattr(subprocess, "DETACHED_PROCESS", 0)),
                )
            except OSError as exc:
                logging.getLogger(__name__).warning(
                    "Cannot start local Supervisor process: %s", type(exc).__name__)
                return None
            _spawned = True
            return None

        if _service_thread is not None and _service_thread.is_alive():
            return _service_thread
        from night_supervisor_service import run_forever
        _service_thread = threading.Thread(
            target=run_forever,
            kwargs={"root": root, "supervisor_factory": supervisor_factory,
                    "stop_event": stop_event},
            name="jarvis-always-on-supervisor",
            daemon=True,
        )
        _service_thread.start()
        return _service_thread

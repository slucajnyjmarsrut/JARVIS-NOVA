# -*- coding: utf-8 -*-
"""Resume only an explicitly approved, unexpired overnight session.

Called after JARVIS GUI startup. No Windows scheduled task, login autostart,
new privileges, or new model installation. The job-specific authorization
and absolute deadline were persisted *before* the original night run.
"""
from __future__ import annotations

import logging
from pathlib import Path
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

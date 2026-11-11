# -*- coding: utf-8 -*-
"""Narrow one-time permission for saving independently tested Python projects.

Only entirely new unique directories under ~/JARVIS-NOVA-Projects are eligible.
Never silently edits an existing user's project, installs dependencies, or
executes generated files on Windows.
"""
from __future__ import annotations

from pathlib import Path
import re

from code_autopilot import AutopilotResult, install_reviewed
from code_quality_review import review_change_plan
from code_workspace import WorkspaceError, preview


def safe_new_project_folder(destination: Path, *, home: Path | None = None) -> bool:
    try:
        root=Path(destination).expanduser()
        owner=Path(home) if home is not None else Path.home()
        base=owner/"JARVIS-NOVA-Projects"
        if (root.exists() or root.is_symlink() or base.is_symlink()
                or not re.fullmatch(r"Project-[a-f0-9]{8}",root.name)):
            return False
        return root.parent.resolve() == base.resolve()
    except (OSError,ValueError,TypeError):
        return False


def save_approved_one_shot(result: AutopilotResult, destination: Path, *,
                           authorized: bool = False, home: Path | None = None):
    """Write verified files once after the user's explicit upfront consent."""
    if authorized is not True:
        raise PermissionError("Автосохранение проекта требует согласия владельца.")
    if not safe_new_project_folder(destination,home=home):
        raise WorkspaceError("Автозапись разрешена только в новую папку JARVIS.")
    if (not isinstance(result,AutopilotResult) or
            result.workspace is not None or not result.verified or
            result.plan.language != "python" or not result.attempts or
            result.attempts[-1].status != "passed" or
            "Docker:" not in result.attempts[-1].diagnostics):
        raise WorkspaceError("Проект не прошёл отдельные функциональные тесты.")
    if review_change_plan(result.plan).risk_count:
        raise WorkspaceError("Потенциально опасный проект требует ручного просмотра.")
    changes=preview(result.plan,destination)
    if any(item["action"] != "create" for item in changes):
        raise WorkspaceError("Автосохранение никогда не заменяет исходные файлы.")
    return install_reviewed(result,destination,confirmed=True)

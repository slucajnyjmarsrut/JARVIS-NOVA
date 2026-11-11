# -*- coding: utf-8 -*-
"""Opt-in Python test gate in a restricted Docker container.

Untrusted model-generated tests NEVER execute on the Windows host. Only a
bounded, sanitized copy of .py files is mounted read-only into an existing,
pinned local container image. Docker isolation is defense-in-depth, not a
proof that arbitrary hostile code cannot escape a container.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from code_workspace import WorkspaceError

IMAGE = "python:3.12-slim"
MAX_FILES = 80
MAX_FILE_BYTES = 250_000
MAX_TOTAL_BYTES = 4_000_000
SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", ".idea", ".vscode",
    "__pycache__", ".pytest_cache", "dist", "build", "site-packages",
    ".jarvis_code_backups", "secrets", ".secrets",
})
SEGMENT = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,80}$")
RUN_COUNT = re.compile(r"Ran\s+(\d+)\s+tests?\s+in\s+", re.I)


@dataclass(frozen=True)
class TestGateReport:
    status: str
    tests_run: int
    output: str
    inspected_files: int
    container_image: str = IMAGE


def _copy_sources(root: Path, staging: Path) -> tuple[int, int]:
    root = Path(root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise WorkspaceError("Нужна обычная локальная папка проекта.")
    root = root.resolve()
    if str(root).startswith("\\\\"):
        raise WorkspaceError("Сетевые папки не запускаются в контейнере.")
    count, total, test_files = 0, 0, 0
    # Walking the tree is bounded and excludes credentials, external dirs,
    # dependency caches and VCS metadata; the original is never mounted.
    for base, dirs, files in os.walk(root, followlinks=False):
        directory = Path(base)
        depth = len(directory.relative_to(root).parts)
        if depth > 5:
            dirs[:] = []
            continue
        dirs[:] = sorted(
            d for d in dirs if d not in SKIP_DIRS and
            not d.startswith(".") and SEGMENT.fullmatch(d) and
            not (directory / d).is_symlink())
        for name in sorted(files):
            file = directory / name
            if (not name.endswith(".py") or not SEGMENT.fullmatch(name)
                    or file.is_symlink() or not file.is_file()):
                continue
            rel = file.relative_to(root)
            count += 1
            size = file.stat().st_size
            total += size
            if (count > MAX_FILES or total > MAX_TOTAL_BYTES
                    or size > MAX_FILE_BYTES):
                raise WorkspaceError("Слишком много кода для ограниченной проверки.")
            output = staging / rel
            output.parent.mkdir(parents=True, exist_ok=True)
            # Never follow a source file that was swapped for a symlink
            # between traversal and read.
            if file.is_symlink() or not file.resolve().is_relative_to(root):
                raise WorkspaceError("Обнаружена ссылка за пределы проекта.")
            output.write_bytes(file.read_bytes())
            output.chmod(0o644)
            if len(rel.parts) >= 2 and rel.parts[0] == "tests" and name.startswith("test_"):
                test_files += 1
    if not test_files:
        return count, 0
    for directory in sorted(staging.rglob("*")):
        if directory.is_dir():
            directory.chmod(0o755)
    staging.chmod(0o755)
    return count, test_files


def _call(executor, args: list[str], timeout: int):
    return executor(
        args, check=False, text=True, capture_output=True,
        stdin=subprocess.DEVNULL, timeout=timeout)


def run_python_tests(
    project_root: Path, *, confirmed: bool = False,
    docker_cli: str | None = None, executor=subprocess.run,
    timeout: int = 120,
) -> TestGateReport:
    """Run tests with a denied network and no source writes; never on host."""
    if confirmed is not True:
        raise PermissionError("Запуск тестов требует явного согласия владельца.")
    if type(timeout) is not int or not 10 <= timeout <= 180:
        raise WorkspaceError("Время тестов должно быть от 10 до 180 секунд.")
    with tempfile.TemporaryDirectory(prefix="nova-review-tests-") as tmp:
        stage = Path(tmp) / "workspace"
        stage.mkdir()
        count, tests = _copy_sources(Path(project_root), stage)
        if not tests:
            return TestGateReport("skipped", 0,
                "Не найдено Python-тестов tests/test_*.py. Функциональность не подтверждена.",
                count)
        cli = docker_cli or shutil.which("docker")
        if not cli:
            return TestGateReport("skipped", 0,
                "Docker не установлен. Код на компьютере НЕ запускался.", count)
        try:
            image_check = _call(executor, [cli, "image", "inspect", IMAGE], 15)
        except (OSError, subprocess.TimeoutExpired):
            return TestGateReport("skipped", 0,
                "Docker недоступен: Python-код не запускался.", count)
        if image_check.returncode:
            return TestGateReport("skipped", 0,
                "Локального образа " + IMAGE +
                " нет. Автоматическая загрузка запрещена; тесты не запускались.", count)
        # No implicit pull, no published ports, no added privileges, no host
        # source mount, no Docker socket mount, no network or writable source.
        container_name = "jarvis-nova-review-" + uuid.uuid4().hex[:16]
        command = [
            cli, "run", "--rm", "--name", container_name,
            "--pull", "never",
            "--network", "none", "--read-only",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "64", "--memory", "512m", "--cpus", "1",
            "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m",
            "--env", "HOME=/tmp", "--env", "PYTHONDONTWRITEBYTECODE=1",
            "--env", "PYTHONPATH=/workspace",
            "--mount", "type=bind,source=" + str(stage) +
                       ",target=/workspace,readonly",
            "--workdir", "/workspace", "--entrypoint", "python", IMAGE,
            "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v",
        ]
        try:
            result = _call(executor, command, timeout)
        except subprocess.TimeoutExpired:
            # Killing the Docker CLI does NOT necessarily stop its container.
            # Force-delete only the uniquely named review container, never
            # other user's containers. The action is bounded too.
            cleanup_ok = False
            try:
                cleanup = _call(
                    executor, [cli, "rm", "-f", container_name], 15)
                cleanup_ok = cleanup.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
            text = (
                "Контейнер превысил лимит времени и был остановлен."
                if cleanup_ok else
                "Контейнер превысил лимит времени. Автоматическая очистка "
                "не подтверждена: проверь Docker-контейнер " + container_name)
            return TestGateReport("failed", 0, text, count)
        except OSError as exc:
            return TestGateReport("skipped", 0,
                "Docker не смог запустить контейнер: " + str(exc)[:250], count)
        output = ((result.stdout or "") + "\n" +
                  (result.stderr or ""))[-12000:]
        match = RUN_COUNT.search(output)
        tests_run = int(match.group(1)) if match else 0
        if result.returncode == 0 and tests_run > 0:
            status = "passed"
        elif not match and result.returncode != 0:
            status = "failed"
            output += "\nКонтейнер не завершил тесты; это НЕ результат проверки кода."
        else:
            status = "failed"
        return TestGateReport(status, tests_run, output, count)

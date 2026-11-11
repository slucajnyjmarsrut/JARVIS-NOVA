# -*- coding: utf-8 -*-
"""Bounded code-generation workflow for Java and Roblox Luau.

A model proposes text files; a human reviews them before any writes.
No shell execution, automatic IDE control, publishing, or silent overwrite.
"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit
from code_workspace import ChangePlan, WorkspaceError, parse_model_proposal, preview, apply_plan
from code_languages import SUPPORTED

SYSTEM = ("You are a senior software engineer building a complete, maintainable project. "
          "Return ONLY valid JSON with exactly keys language and files; files is "
          "an array of {path,content}. The language must exactly match the user's "
          "requested language. No markdown fences, no invented test results or "
          "shell commands to execute. Build multi-file architecture with meaningful "
          "modules, useful tests, error handling, docs and a README. Prefer "
          "standard libraries; record required dependencies but do not install them. "
          "For Roblox create Luau scripts and explain Rojo/Studio placement, "
          "models and map generation. Never embed secrets or API keys. "
          "Never claim to have tested or launched code unless validated by tools.")

@dataclass(frozen=True)
class CodeResult:
    plan: ChangePlan
    changes: list[dict]


class _RejectModelRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        # Any redirect risks exfiltrating generated/user source text to
        # third-party hosts. Never follow even another loopback address.
        raise WorkspaceError(
            'Локальная модель предложила перенаправление: передача отменена.')


def request_local_model(task: str, language: str, *, endpoint: str = 'http://127.0.0.1:11434',
                        model: str = 'qwen2.5-coder:7b', transport=None) -> str:
    """Only loopback Ollama is supported; no user code is sent to the cloud."""
    if language not in SUPPORTED or not isinstance(task, str) or not 1 <= len(task.strip()) <= 20000:
        raise WorkspaceError('Некорректная задача или язык')
    try:
        parsed = urlsplit(endpoint)
        valid = (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
                 and parsed.port is not None and 1 <= parsed.port <= 65535
                 and not parsed.path and not parsed.query and not parsed.fragment
                 and parsed.username is None and parsed.password is None)
    except ValueError:
        valid = False
    if not valid:
        raise WorkspaceError('Разрешена только локальная Ollama на 127.0.0.1')
    if (not isinstance(model,str) or
            re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}',model) is None):
        raise WorkspaceError('Недопустимое имя локальной модели.')
    payload = {'model': model, 'stream': False, 'format': 'json',
               'messages': [{'role': 'system', 'content': SYSTEM},
                            {'role': 'user', 'content': f'Language: {language}\nTask: {task}'}],
               'options': {'temperature': 0.1, 'num_predict': 8192}}
    if transport is None:
        def transport(url, data):
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _RejectModelRedirect())
            req = urllib.request.Request(url, json.dumps(data).encode('utf-8'),
                                         {'Content-Type': 'application/json'}, method='POST')
            with opener.open(req, timeout=180) as response:
                body = response.read(500_001)
            if len(body) > 500_000:
                raise WorkspaceError('Ответ модели слишком длинный')
            return json.loads(body)
    result = transport(endpoint + '/api/chat', payload)
    if not isinstance(result, dict) or not isinstance(result.get('message'), dict):
        raise WorkspaceError('Некорректный ответ Ollama')
    content = result['message'].get('content')
    if not isinstance(content, str):
        raise WorkspaceError('Модель не вернула текст проекта')
    return content


def propose(task: str, language: str, root: Path, *, generator=request_local_model) -> CodeResult:
    raw = generator(task, language)
    plan = parse_model_proposal(raw)
    if plan.language != language:
        raise WorkspaceError('Модель вернула другой язык')
    return CodeResult(plan, preview(plan, root))


def approve_and_write(result: CodeResult, root: Path, *, approved: bool = False) -> list[str]:
    if not approved:
        raise PermissionError('Подтверди запись файлов после просмотра плана')
    return apply_plan(result.plan, root, confirmed=True)


def check_java(root: Path, *, timeout: int = 30) -> dict:
    """Compile .java files using installed javac, without executing generated programs.

    Build outputs are created in a temporary directory, not in the source tree.
    """
    root = Path(root).resolve()
    sources = sorted(root.rglob('*.java'))
    if not sources:
        return {'status': 'skipped', 'reason': 'Нет Java-файлов'}
    if len(sources) > 100 or any(p.is_symlink() or not p.resolve().is_relative_to(root) for p in sources):
        raise WorkspaceError('Недопустимый набор Java-файлов')
    import shutil
    javac = shutil.which('javac')
    if not javac:
        return {'status': 'skipped', 'reason': 'JDK (javac) не установлен'}
    with tempfile.TemporaryDirectory(prefix='jarvis-javac-') as output:
        try:
            result = subprocess.run([javac, '-proc:none', '-encoding', 'UTF-8', '-classpath', output, '-d', output, *map(str, sources)],
                                    capture_output=True, text=True, timeout=timeout,
                                    shell=False, cwd=str(root))
        except subprocess.TimeoutExpired:
            return {'status': 'failed', 'reason': 'Превышено время компиляции'}
    return {'status': 'passed' if result.returncode == 0 else 'failed',
            'exit_code': result.returncode,
            'diagnostics': (result.stdout + '\n' + result.stderr)[-6000:]}


def check_luau(root: Path) -> dict:
    """Static file checks only; Roblox Studio playtest remains necessary."""
    root = Path(root).resolve()
    scripts = list(root.rglob('*.luau')) + list(root.rglob('*.lua'))
    if not scripts:
        return {'status': 'skipped', 'reason': 'Нет Luau-файлов'}
    for path in scripts:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise WorkspaceError('Недопустимый путь скрипта')
        content = path.read_text(encoding='utf-8')
        if not content.strip() or '\x00' in content:
            return {'status': 'failed', 'reason': f'Пустой или повреждённый файл: {path.name}'}
    import shutil
    compiler = shutil.which('luau-compile')
    if compiler:
        for path in scripts:
            try:
                outcome = subprocess.run([compiler, str(path)], capture_output=True, timeout=15, shell=False)
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {'status': 'failed', 'reason': 'Проверка Luau не завершилась: '+str(exc)[:200]}
            if outcome.returncode:
                return {'status': 'failed', 'reason': (outcome.stderr or outcome.stdout).decode('utf-8', errors='replace')[-3000:]}
        return {'status': 'partial', 'reason': 'Luau-компилятор принял файлы; Roblox Studio Play Test не запускался', 'scripts': len(scripts)}
    return {'status': 'partial', 'reason': 'Файлы читаются; синтаксис и выполнение в Roblox Studio не проверены',
            'scripts': len(scripts)}

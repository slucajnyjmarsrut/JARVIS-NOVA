# -*- coding: utf-8 -*-
"""Safe project scaffolding and reviewable AI-generated changes for JARVIS NOVA.

No arbitrary shell commands, automatic publishing or silent overwrites.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json
import re

class WorkspaceError(ValueError):
    pass

@dataclass(frozen=True)
class ProposedFile:
    path: str
    content: str

@dataclass(frozen=True)
class ChangePlan:
    language: str
    files: tuple[ProposedFile, ...]

from code_languages import SUPPORTED, EXTENSIONS, starter_files
MAX_FILES = 100
MAX_BYTES = 500_000
WINDOWS_RESERVED = frozenset({'CON', 'PRN', 'AUX', 'NUL', *[f'COM{x}' for x in range(1,10)], *[f'LPT{x}' for x in range(1,10)]})

def _relative_path(raw: str, language: str) -> Path:
    if not isinstance(raw, str) or not raw or len(raw) > 180 or '\\' in raw or '\x00' in raw:
        raise WorkspaceError('Некорректное имя файла')
    p = Path(raw)
    if p.is_absolute() or any(x in ('.', '..') for x in raw.split('/')) or ':' in raw:
        raise WorkspaceError('Путь выходит за пределы проекта')
    if any(not re.fullmatch(r'[\w. -]+', part, re.UNICODE) or part.startswith('.') and part not in ('.gitignore',) for part in p.parts):
        raise WorkspaceError('Недопустимое имя файла')
    if any(part.endswith((' ', '.')) or part.split('.')[0].upper() in WINDOWS_RESERVED for part in p.parts):
        raise WorkspaceError('Недопустимое имя файла Windows')
    if p.suffix.lower() not in EXTENSIONS[language]:
        raise WorkspaceError('Недопустимый тип файла')
    return p

def validate_plan(plan: ChangePlan) -> ChangePlan:
    if plan.language not in SUPPORTED or not 1 <= len(plan.files) <= MAX_FILES:
        raise WorkspaceError('Неподдерживаемый язык или количество файлов')
    seen = set()
    total = 0
    for item in plan.files:
        p = _relative_path(item.path, plan.language)
        if str(p).casefold() in seen:
            raise WorkspaceError('Повторяющийся путь')
        seen.add(str(p).casefold())
        if not isinstance(item.content, str) or '\x00' in item.content:
            raise WorkspaceError('Недопустимое содержимое')
        total += len(item.content.encode('utf-8'))
    if total > MAX_BYTES:
        raise WorkspaceError('Слишком большой проект')
    return plan

def preview(plan: ChangePlan, root: Path) -> list[dict]:
    validate_plan(plan)
    original_base = Path(root).absolute()
    if original_base.is_symlink():
        raise WorkspaceError('Каталог проекта не может быть символической ссылкой')
    base = original_base.resolve()
    changes = []
    for item in plan.files:
        path = base / _relative_path(item.path, plan.language)
        if path.is_symlink() or any(parent.is_symlink() for parent in list(path.parents) if parent != base and base in parent.parents):
            raise WorkspaceError('Символические ссылки запрещены')
        if not path.resolve().is_relative_to(base):
            raise WorkspaceError('Путь вне проекта')
        changes.append({'path': item.path, 'action': 'replace' if path.exists() else 'create'})
    return changes

def apply_plan(plan: ChangePlan, root: Path, *, confirmed: bool = False) -> list[str]:
    """Only write after explicit approval; never overwrite an existing file."""
    if not confirmed:
        raise PermissionError('Нужно подтверждение изменения файлов')
    original_base = Path(root).absolute()
    if original_base.is_symlink():
        raise WorkspaceError('Каталог проекта не может быть символической ссылкой')
    base = original_base.resolve()
    changes = preview(plan, base)
    if any(change['action'] == 'replace' for change in changes):
        raise WorkspaceError('Существующие файлы не перезаписываются автоматически')
    base.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        for item in plan.files:
            path = base / _relative_path(item.path, plan.language)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive create prevents accidental overwrite even if the file appears after preview.
            with path.open('x', encoding='utf-8', newline='\n') as f:
                f.write(item.content)
            written.append(path)
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise
    return [str(path) for path in written]

def starter_project(language: str, name: str) -> ChangePlan:
    if language not in SUPPORTED or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,39}', name):
        raise WorkspaceError('Недопустимый язык или название проекта')
    if language == 'java':
        return ChangePlan('java', (
            ProposedFile(f'src/main/java/{name}/Main.java',
                f'package {name};\n\npublic final class Main {{\n    public static void main(String[] args) {{\n        System.out.println("JARVIS NOVA: {name}");\n    }}\n}}\n'),
            ProposedFile('README.md', f'# {name}\n\nJava starter project. Compile with javac from the project root.\n'),
        ))
    if language != 'luau':
        entries=starter_files(language,name)
        return validate_plan(ChangePlan(language,(
            *(ProposedFile(path,content) for path,content in entries),
            ProposedFile('README.md',
                f'# {name}\n\nStarter project ({language}). '
                'No tests or executable code run automatically. '
                'Check dependencies and configuration before deploying.\n'),
        )))
    return ChangePlan('luau', (
            f'-- {name}: Roblox server entry point\nprint("JARVIS NOVA: {name}")\n'),
        ProposedFile('default.project.json', '{\n  \"name\": \"'+name+'\",\n  \"tree\": {\n    \"$className\": \"DataModel\",\n    \"ServerScriptService\": {\n      \"$className\": \"ServerScriptService\",\n      \"Main\": {\n        \"$path\": \"src/server/Main.server.luau\"\n      }\n    }\n  }\n}\n'),
        ProposedFile('README.md', f'# {name}\n\nRoblox Studio: import `src/server/Main.server.luau` into ServerScriptService, or use Rojo with `default.project.json`. Test with Play in Roblox Studio before publishing.\n'),
    ))

def parse_model_proposal(raw: str) -> ChangePlan:
    """Strictly parse model output; model text is data, never an executable command."""
    if not isinstance(raw, str) or len(raw) > MAX_BYTES * 2:
        raise WorkspaceError('Слишком длинный ответ модели')
    try:
        obj = json.loads(raw)
        if set(obj) != {'language', 'files'} or not isinstance(obj['files'], list):
            raise ValueError('schema')
        files = []
        for item in obj['files']:
            if not isinstance(item, dict) or set(item) != {'path', 'content'}:
                raise ValueError('file schema')
            files.append(ProposedFile(item['path'], item['content']))
        return validate_plan(ChangePlan(obj['language'], tuple(files)))
    except (ValueError, TypeError, KeyError) as exc:
        raise WorkspaceError('Неверный формат проекта от модели') from exc

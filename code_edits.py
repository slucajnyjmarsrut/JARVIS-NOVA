# -*- coding: utf-8 -*-
"""Bounded, reviewable edits of existing Java/Luau projects.

Generated code is data. Existing files are replaced only after explicit approval,
while backups are retained for recovery; no shell or generated code is executed.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib
import os
import shutil
import tempfile

from code_workspace import ChangePlan, WorkspaceError, _relative_path, validate_plan, preview, EXTENSIONS

MAX_CONTEXT_FILES = 24
MAX_CONTEXT_BYTES = 80_000


def _project_files(root: Path, language: str) -> list[Path]:
    if language not in EXTENSIONS:
        raise WorkspaceError('Неизвестный язык')
    root=Path(root)
    if root.is_symlink() or not root.is_dir():
        raise WorkspaceError('Для правок выбери существующую обычную папку проекта')
    base=root.resolve()
    result=[]
    # Don't traverse hidden metadata or backup directories, which could contain
    # old source versions and duplicate compiled class names.
    for dirname,dirs,files in os.walk(base,followlinks=False):
        location=Path(dirname)
        for child in dirs:
            if (location/child).is_symlink():
                raise WorkspaceError('Символические ссылки в каталогах запрещены')
        dirs[:]=[d for d in dirs if not d.startswith('.') and d not in
                 ('build','target','out','dist','node_modules','.jarvis_code_backups')]
        for filename in sorted(files):
            path=location/filename
            if path.is_symlink():
                raise WorkspaceError('Символические ссылки в файлах запрещены')
            if path.suffix.lower() not in EXTENSIONS[language]:
                continue
            rel=path.relative_to(base)
            _relative_path(rel.as_posix(),language)
            result.append(path)
            if len(result)>MAX_CONTEXT_FILES:
                raise WorkspaceError('В проекте слишком много файлов для безопасного обзора')
    return sorted(result)


def snapshot_project(root: Path, language: str) -> tuple[str,dict[str,str]]:
    """Return bounded local context and immutable hashes for concurrency checks."""
    base=Path(root).resolve()
    files=_project_files(root,language)
    contents=[];digests={};size=0
    for file in files:
        data=file.read_bytes()
        size+=len(data)
        if size>MAX_CONTEXT_BYTES:raise WorkspaceError('Проект слишком большой для безопасного обзора')
        try:content=data.decode('utf-8')
        except UnicodeError as exc:raise WorkspaceError('Файл не в UTF-8') from exc
        rel=file.relative_to(base).as_posix()
        digests[rel]=hashlib.sha256(data).hexdigest()
        contents.append(f'FILE {rel}:\n{content}\nEND FILE')
    return '\n'.join(contents),digests


def stage_project(root: Path, destination: Path, language: str) -> None:
    """Copy only bounded readable code/data files, no executables or symlinks."""
    base=Path(root).resolve()
    for source in _project_files(root,language):
        rel=source.relative_to(base)
        target=destination/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)


def write_reviewed_update(plan: ChangePlan, root: Path, expected_sha: dict[str,str],
                          *, confirmed: bool=False) -> list[str]:
    """Approve exact modified bytes, preserve original files and reject races."""
    if not confirmed:raise PermissionError('Сначала подтверди изменения')
    validate_plan(plan)
    base=Path(root)
    if base.is_symlink():raise WorkspaceError('Каталог проекта не может быть ссылкой')
    base=base.resolve()
    changes=preview(plan,base)
    if any(p.is_symlink() for p in (base/'.jarvis_code_backups',)):
        raise WorkspaceError('Папка копий не должна быть ссылкой')
    for item in plan.files:
        path=base/_relative_path(item.path,plan.language)
        before=expected_sha.get(item.path)
        if path.exists():
            if before is None or not path.is_file():
                raise WorkspaceError(f'Существующий файл не был в исходном обзоре: {item.path}')
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            if digest!=before:raise WorkspaceError(f'Файл изменился после проверки: {item.path}')
        elif before is not None:
            raise WorkspaceError(f'Исходный файл удалён: {item.path}')
    backups=base/'.jarvis_code_backups'
    previous=[(base/_relative_path(item.path,plan.language),
               (base/_relative_path(item.path,plan.language)).read_bytes()
               if (base/_relative_path(item.path,plan.language)).exists() else None)
              for item in plan.files]
    backups.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.pending-',dir=str(base)) as pending:
        pending=Path(pending)
        for item in plan.files:
            file=pending/_relative_path(item.path,plan.language)
            file.parent.mkdir(parents=True,exist_ok=True)
            file.write_text(item.content,encoding='utf-8',newline='\n')
        revision=Path(tempfile.mkdtemp(prefix='revision-',dir=str(backups)))
        for file,bytes_before in previous:
            if bytes_before is not None:
                saved=revision/file.relative_to(base)
                saved.parent.mkdir(parents=True,exist_ok=True)
                saved.write_bytes(bytes_before)
        changed=[]
        try:
            for item in plan.files:
                target=base/_relative_path(item.path,plan.language)
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    # Only replace exact reviewed, hash-locked targets.
                    existing=hashlib.sha256(target.read_bytes()).hexdigest()
                    if existing!=expected_sha[item.path]:
                        raise WorkspaceError(f'Файл изменился во время записи: {item.path}')
                elif item.path in expected_sha:
                    raise WorkspaceError(f'Файл был удалён во время записи: {item.path}')
                # Move staging across dirs in same filesystem; destination safely checked.
                os.replace(pending/_relative_path(item.path,plan.language),target)
                changed.append(target)
        except Exception:
            for target in reversed(changed):
                old=dict(previous)[target]
                if old is None:target.unlink(missing_ok=True)
                else:target.write_bytes(old)
            raise
    return [str(base/_relative_path(item.path,plan.language)) for item in plan.files]

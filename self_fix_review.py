# -*- coding: utf-8 -*-
"""Explain and conservatively audit a proposed one-file NOVA UI change.

This is defense in depth, NOT proof that generated code is harmless:
Python can execute arbitrary effects by many routes. The proposal must still
be reviewed by the owner, tested in CI, and never auto-published.
"""
from __future__ import annotations

import ast
from collections import Counter
from difflib import unified_diff

from code_workspace import WorkspaceError

# Calls with possible execution, disk mutation, secrets or network effects.
# Existing occurrences may be preserved verbatim; newly added/altered ones
# require a human developer outside the autonomous proposal workflow.
DANGEROUS_CALLS = frozenset({
    "eval", "exec", "compile", "__import__", "open", "input",
    "breakpoint", "getattr", "setattr", "delattr", "globals", "locals", "vars",
    "os.system", "os.popen", "os.startfile", "os.remove", "os.unlink",
    "os.replace", "os.rename", "os.chmod", "os.chown",
    "os.execv", "os.execve", "os.spawnv", "os.spawnve",
    "shutil.rmtree", "shutil.move", "shutil.copy2",
    "subprocess.run", "subprocess.call", "subprocess.check_call",
    "subprocess.check_output", "subprocess.Popen",
    "socket.socket", "socket.create_connection",
    "urllib.request.urlopen", "urllib.request.Request",
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "httpx.get", "httpx.post", "os.getenv", "os.environ.get",
    "pathlib.Path.open", "pathlib.Path.unlink", "pathlib.Path.write_text",
    "pathlib.Path.write_bytes", "pathlib.Path.replace",
    "Path.open", "Path.unlink", "Path.write_text", "Path.write_bytes",
    "Path.replace", "Path.rename", "Path.mkdir",
    "importlib.import_module",
})
DANGEROUS_SUFFIXES = frozenset({
    ".open", ".write_text", ".write_bytes", ".unlink",
    ".rmdir", ".rename", ".replace", ".chmod",
    ".request", ".post", ".put", ".delete", ".get",
    ".connect", ".send", ".sendall", ".load_library",
    ".eval", ".exec", ".system", ".popen",
})
SENSITIVE_IMPORTS = frozenset({
    "subprocess", "socket", "requests", "httpx", "ctypes",
    "importlib", "pickle", "marshal", "multiprocessing", "webbrowser",
    "shutil", "urllib.request", "urllib3", "ftplib", "smtplib",
})
DANGEROUS_ACCESS = frozenset({
    "__dict__", "__class__", "__bases__", "__subclasses__",
    "__globals__", "__code__", "__builtins__",
})


def _qualified_name(expr: ast.AST) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        lhs = _qualified_name(expr.value)
        return lhs + "." + expr.attr if lhs else expr.attr
    return ""


def _dangerous_inventory(text: str) -> Counter:
    parsed = ast.parse(text)
    found = Counter()
    for node in ast.walk(parsed):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            else:
                names = [node.module or ""]
            if any(n == prefix or n.startswith(prefix + ".")
                   for n in names for prefix in SENSITIVE_IMPORTS):
                found["import: " + ast.unparse(node)] += 1
        elif isinstance(node, ast.Call):
            name = _qualified_name(node.func)
            if (name in DANGEROUS_CALLS or
                    any(name.endswith(suffix) for suffix in DANGEROUS_SUFFIXES) or
                    name.startswith(("subprocess.", "socket.", "requests.",
                                     "httpx.", "urllib.", "importlib."))):
                found["call: " + ast.unparse(node)] += 1
        elif isinstance(node, ast.Attribute) and node.attr in DANGEROUS_ACCESS:
            found["access: " + ast.unparse(node)] += 1
    return found


def audit_source_change(original: str, proposed: str) -> tuple[str, ...]:
    """Reject new risky AST operations; never execute user/model Python."""
    old = _dangerous_inventory(original)
    new = _dangerous_inventory(proposed)
    additions = new - old
    if additions:
        first = next(iter(additions)).replace("\n", " ")[:160]
        raise WorkspaceError(
            "Предложение добавляет или изменяет потенциально опасную операцию: "
            + first + ". Для таких изменений нужен ручной разбор разработчиком.")
    if len(proposed.encode("utf-8")) > 44_000:
        raise WorkspaceError("Предложенная версия файла слишком большая.")
    return (
        "Python AST: синтаксис проверен без выполнения кода.",
        "Новых выявленных операций запуска, записи файлов или сети нет.",
        "Проверка не доказывает безопасность или работоспособность. "
        "Нужны ревью и Windows-тесты.",
    )


def show_diff(filename: str, original: str, proposed: str) -> str:
    """Full unified diff, never hide changes at the bottom of the preview."""
    return "".join(unified_diff(
        original.splitlines(keepends=True),
        proposed.splitlines(keepends=True),
        fromfile="jarvis/до/" + filename,
        tofile="jarvis/после/" + filename,
        n=4,
    ))

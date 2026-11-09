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
    ".rmdir", ".chmod",
    ".request", ".connect", ".send", ".sendall", ".load_library",
    ".eval", ".exec", ".system", ".popen",
})
SENSITIVE_IMPORTS = frozenset({
    "subprocess", "socket", "requests", "httpx", "ctypes",
    "importlib", "pickle", "marshal", "multiprocessing", "webbrowser",
    "shutil", "urllib.request", "urllib3", "ftplib", "smtplib",
    "os", "pathlib", "builtins", "sys", "zipfile", "tarfile",
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


def _import_aliases(parsed: ast.AST) -> dict[str, str]:
    """Resolve direct aliases used to disguise sensitive module calls."""
    aliases = {}
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split(".")[0]] = (
                    item.name if item.asname else item.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for item in node.names:
                if node.module:
                    aliases[item.asname or item.name] = node.module + "." + item.name
    return aliases


def _canonical_call(node: ast.Call, aliases: dict[str, str]) -> str:
    name = _qualified_name(node.func)
    root, separator, rest = name.partition(".")
    if root in aliases:
        return aliases[root] + (separator + rest if separator else "")
    return name


def _risky_node(node: ast.AST, aliases: dict[str, str]) -> bool:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""])
        return any(name == sensitive or name.startswith(sensitive + ".")
                   for name in names for sensitive in SENSITIVE_IMPORTS)
    if isinstance(node, ast.Call):
        name = _canonical_call(node, aliases)
        return (name in DANGEROUS_CALLS or
                any(name.endswith(suffix) for suffix in DANGEROUS_SUFFIXES) or
                name.startswith(("subprocess.", "socket.", "requests.",
                                 "httpx.", "urllib.", "importlib.")))
    return isinstance(node, ast.Attribute) and node.attr in DANGEROUS_ACCESS


def _import_inventory(parsed: ast.AST) -> Counter:
    return Counter(ast.unparse(node) for node in ast.walk(parsed)
                   if isinstance(node, (ast.Import, ast.ImportFrom)))


def _protected_scope_inventory(parsed: ast.AST) -> Counter:
    """Freeze functions containing sensitive operations at their AST location."""
    aliases = _import_aliases(parsed)
    result = Counter()

    class Walk(ast.NodeVisitor):
        def __init__(self):
            self.stack = []

        def _visit_scope(self, node):
            path = "::".join((*self.stack, node.name))
            if any(_risky_node(child, aliases) for child in ast.walk(node)):
                result[(path, ast.dump(node, include_attributes=False))] += 1
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_ClassDef(self, node):
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        visit_FunctionDef = _visit_scope
        visit_AsyncFunctionDef = _visit_scope

    Walk().visit(parsed)
    return result


def _dangerous_inventory(text: str) -> Counter:
    parsed = ast.parse(text)
    aliases = _import_aliases(parsed)
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
            if _risky_node(node, aliases):
                found["call: " + ast.unparse(node)] += 1
        elif isinstance(node, ast.Attribute) and node.attr in DANGEROUS_ACCESS:
            found["access: " + ast.unparse(node)] += 1
    return found


def audit_source_change(original: str, proposed: str) -> tuple[str, ...]:
    """Reject new risky AST operations; never execute user/model Python."""
    old_tree = ast.parse(original)
    new_tree = ast.parse(proposed)
    # Any newly imported module may execute arbitrary code at import time.
    # For self-modification, adding even a benign import needs human review.
    imports_added = _import_inventory(new_tree) - _import_inventory(old_tree)
    if imports_added:
        raise WorkspaceError(
            "Предложение добавляет импорт модуля: " +
            next(iter(imports_added))[:160] + ". Нужна ручная проверка.")
    old = _dangerous_inventory(original)
    new = _dangerous_inventory(proposed)
    additions = new - old
    if additions:
        first = next(iter(additions)).replace("\n", " ")[:160]
        raise WorkspaceError(
            "Предложение добавляет или изменяет потенциально опасную операцию: "
            + first + ". Для таких изменений нужен ручной разбор разработчиком.")
    # A risky call can be moved without changing the global inventory.
    # Forbid changed or relocated functions containing any such operation.
    before_scopes = _protected_scope_inventory(old_tree)
    after_scopes = _protected_scope_inventory(new_tree)
    if before_scopes != after_scopes:
        raise WorkspaceError(
            "Изменена функция, содержащая чувствительные операции. "
            "Эти изменения требуют отдельного ручного аудита.")
    if len(proposed.encode("utf-8")) > 44_000:
        raise WorkspaceError("Предложенная версия файла слишком большая.")
    return (
        "Python AST: синтаксис проверен без выполнения кода.",
        "Новых выявленных операций запуска, записи файлов или сети нет.",
        "Проверка не доказывает безопасность или работоспособность. "
        "Нужны ревью и Windows-тесты.",
    )


def show_diff(filename: str, original: str, proposed: str) -> str:
    """Full unified diff with normalized Windows CRLF for a readable preview.

    Only presentation is normalized. Hash checks and backup bytes retain
    their original line endings for faithful restoration.
    """
    before = original.replace("\r\n", "\n").replace("\r", "\n")
    after = proposed.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="jarvis/до/" + filename,
        tofile="jarvis/после/" + filename,
        n=4,
    ))

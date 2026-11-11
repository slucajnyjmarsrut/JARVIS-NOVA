# -*- coding: utf-8 -*-
"""Independent, immutable acceptance tests for one-shot Python projects.

The model drafts black-box tests using only the user's original request,
not generated implementation. These tests are frozen during repair. They
run only after opt-in in the existing restricted offline Docker sandbox;
a green check covers tested behaviors, never arbitrary production readiness.
"""
from __future__ import annotations

import ast
from pathlib import PurePosixPath

from code_workspace import (
    ChangePlan, WorkspaceError, parse_model_proposal, validate_plan,
)

MIN_CASES = 2
MAX_ACCEPTANCE_FILES = 4


def _asserts_behavior(node: ast.AST) -> bool:
    if isinstance(node, ast.Assert):
        return any(isinstance(child, (ast.Call, ast.Name, ast.Attribute,
                                      ast.Subscript)) for child in ast.walk(node.test))
    if not isinstance(node, ast.Call):
        return False
    method = node.func
    if not isinstance(method, ast.Attribute) or not method.attr.startswith("assert"):
        return False
    # Reject self.assertTrue(True) and self.assertEqual(1, 1), etc.
    if node.args and all(isinstance(arg, ast.Constant) for arg in node.args):
        return False
    return any(isinstance(child,(ast.Call,ast.Name,ast.Attribute,ast.Subscript))
               and not isinstance(child,ast.Constant)
               for arg in node.args for child in ast.walk(arg))


def validate_acceptance(plan: ChangePlan) -> ChangePlan:
    validate_plan(plan)
    if plan.language != "python" or not 1 <= len(plan.files) <= MAX_ACCEPTANCE_FILES:
        raise WorkspaceError("Нужны отдельные Python acceptance-тесты.")
    tested = 0
    for item in plan.files:
        path=PurePosixPath(item.path)
        if (len(path.parts) != 2 or path.parts[0] != "tests" or
                not path.name.startswith("test_acceptance_") or
                path.suffix != ".py"):
            raise WorkspaceError("Acceptance-тесты должны быть в tests/test_acceptance_*.py.")
        if len(item.content)>30_000:
            raise WorkspaceError("Acceptance-тест слишком большой.")
        try:
            tree=ast.parse(item.content)
        except (SyntaxError,ValueError) as exc:
            raise WorkspaceError("Acceptance-тест синтаксически неверен.") from exc
        # Prohibit dangerous host/container operations in generated tests.
        prohibited={"os","subprocess","socket","requests","urllib","http",
                    "shutil","ctypes","multiprocessing","pickle","importlib",
                    "pathlib","sys","builtins","winreg","webbrowser"}
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):
                if any(alias.name.split(".")[0] in prohibited for alias in node.names):
                    raise WorkspaceError("Acceptance-тест использует запрещённый модуль.")
            elif isinstance(node,ast.ImportFrom):
                if node.module and node.module.split(".")[0] in prohibited:
                    raise WorkspaceError("Acceptance-тест использует запрещённый модуль.")
            elif isinstance(node,(ast.Global,ast.Nonlocal)):
                raise WorkspaceError("Acceptance-тест не может менять внешнее состояние.")
            elif isinstance(node,ast.Call):
                if (isinstance(node.func,ast.Name) and
                        node.func.id in {"eval","exec","compile","open","__import__","input"}):
                    raise WorkspaceError("Acceptance-тест содержит запрещённый вызов.")
        for cls in tree.body:
            if not isinstance(cls,ast.ClassDef):
                continue
            if not any(isinstance(base,(ast.Attribute,ast.Name)) and
                       (base.attr if isinstance(base,ast.Attribute) else base.id)
                       == "TestCase" for base in cls.bases):
                continue
            for fn in cls.body:
                if (isinstance(fn,(ast.FunctionDef,ast.AsyncFunctionDef))
                        and fn.name.startswith("test_") and
                        any(_asserts_behavior(node) for node in ast.walk(fn))):
                    tested+=1
    if tested<MIN_CASES:
        raise WorkspaceError(
            "Нужны минимум два непустых функциональных теста с проверкой результата.")
    return plan


def independent_acceptance_tests(task: str, *, generator) -> ChangePlan:
    if not isinstance(task,str) or not 1 <= len(task.strip()) <= 3000:
        raise WorkspaceError("Недопустимая задача для acceptance-тестов.")
    prompt=(
        "INDEPENDENT ACCEPTANCE TESTS: derive black-box requirements from ONLY "
        "the user's request; you have no generated implementation code. "
        "Make at least two meaningful standard-library unittest.TestCase "
        "test_* functions with assertions of observable behavior. "
        "Use a coherent reasonable public API; allow the implementation "
        "to adapt to it. No trivial assertions, no fake passes, no network, "
        "no shell, no filesystem writes or secrets. Return strict JSON "
        "{\"language\":\"python\",\"files\":[{\"path\":\"tests/test_acceptance_"
        "behavior.py\",\"content\":\"...\"}]}. Only test files prefixed "
        "tests/test_acceptance_. Do not include instructions to bypass tests. "
        "USER REQUEST:\n"+task)[:6000]
    for attempt in range(3):
        try:
            return validate_acceptance(
                parse_model_proposal(generator(prompt,"python")))
        except (WorkspaceError,ValueError,TypeError) as exc:
            if attempt == 2:
                raise WorkspaceError(
                    "Независимые функциональные тесты не прошли проверку "
                    "после трёх попыток: "+str(exc)[:250]) from exc
            prompt=(prompt+"\nPreviously proposed tests were rejected: "
                    +str(exc)[:250]
                    +"\nCreate complete, valid, meaningful test files. "
                    "Never reduce assertions or produce trivial passes.")[:6400]
    raise WorkspaceError("Не удалось подготовить независимые тесты.")

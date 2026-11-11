# -*- coding: utf-8 -*-
"""Mutation gate for independent Python acceptance tests.

After a project passes real Docker tests, deliberately damage one public
source function in a DISPOSABLE review plan and re-run ONLY the independent
acceptance tests in the already authorized offline Docker sandbox.
If those tests still pass, they cannot certify that functionality.
Never mutate the user workspace or copy model output to the host executor.
This measures only one mutation, NOT full behavioral correctness.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from code_workspace import (
    ChangePlan, ProposedFile, WorkspaceError, validate_plan,
)


@dataclass(frozen=True)
class MutationResult:
    detected: bool
    cases: int
    target: str
    diagnostics: str


def _test_imports(plan: ChangePlan):
    names=set()
    for file in plan.files:
        if not file.path.startswith("tests/test_acceptance_"):
            continue
        try:
            tree=ast.parse(file.content)
        except (ValueError,SyntaxError) as exc:
            raise WorkspaceError("Независимый тест повреждён.") from exc
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):
                for member in node.names:
                    if member.name!="*":
                        names.add(member.name)
    return names


def acceptance_mutant(plan: ChangePlan):
    """Return a new plan with one function's return value replaced by None.

    Only original application sources are mutated, never a test. Prefer
    functions imported by independent tests, to avoid irrelevant mutations.
    The original ChangePlan object and user files remain untouched.
    """
    validate_plan(plan)
    if plan.language!="python":
        raise WorkspaceError("Mutation gate поддерживает Python.")
    referenced=_test_imports(plan)
    candidates=[]
    for file in plan.files:
        if not file.path.endswith(".py") or file.path.startswith("tests/"):
            continue
        try:
            tree=ast.parse(file.content)
        except (SyntaxError,ValueError):
            continue
        for node in tree.body:
            methods=[]
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                methods=[(None,node)]
            elif isinstance(node,ast.ClassDef):
                methods=[(node.name,method) for method in node.body
                         if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef))
                         and not method.name.startswith("__")]
            for owner,fn in methods:
                returns=[child for child in ast.walk(fn)
                         if isinstance(child,ast.Return) and child.value is not None]
                if returns:
                    score=int((owner or fn.name) in referenced)
                    candidates.append((score,file,owner,fn.name))
    if not candidates:
        raise WorkspaceError("Нет проверяемой Python-функции для mutation gate.")
    _,chosen,owner,name=max(candidates,key=lambda item:item[0])
    tree=ast.parse(chosen.content)
    if owner is None:
        target=next(node for node in tree.body
                    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
                    and node.name==name)
    else:
        cls=next(node for node in tree.body
                 if isinstance(node,ast.ClassDef) and node.name==owner)
        target=next(node for node in cls.body
                    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
                    and node.name==name)
    class BreakOneReturn(ast.NodeTransformer):
        done=False
        def visit_Return(self,node):
            if not self.done and node.value is not None:
                self.done=True
                return ast.copy_location(
                    ast.Return(value=ast.Constant(value=None)),node)
            return node
        def visit_FunctionDef(self,node):
            # Avoid mutating nested helper functions, only selected return.
            return self.generic_visit(node)
    mutation=BreakOneReturn()
    mutation.visit(target)
    if not mutation.done:
        raise WorkspaceError("Не удалось создать проверочную мутацию.")
    altered=ast.unparse(ast.fix_missing_locations(tree))+"\n"
    files=[]
    for file in plan.files:
        if file.path.startswith("tests/"):
            if file.path.startswith("tests/test_acceptance_"):
                files.append(file)
        elif file.path==chosen.path:
            files.append(ProposedFile(file.path,altered))
        else:
            files.append(file)
    return validate_plan(ChangePlan("python",tuple(files))), (
        chosen.path+":"+(owner+"." if owner else "")+name
    )


def verify_independent_tests(plan: ChangePlan, *, runner, confirmed=False):
    """Real (or injected) runner must show at least 2 failed acceptance tests."""
    if confirmed is not True:
        raise PermissionError("Мутационный тест требует разрешения на Docker.")
    from code_test_repair import _test_plan
    mutant,target=acceptance_mutant(plan)
    report=_test_plan(mutant,runner,confirmed=True)
    # A process crash without a unittest summary is NOT evidence that
    # assertions detected a broken implementation.
    assertions_failed=bool(re.search(
        r"(?m)^FAIL:\s+test_[A-Za-z0-9_]+",str(report.output)))
    detected=(report.status=="failed" and report.tests_run>=2
              and assertions_failed)
    return MutationResult(
        bool(detected),report.tests_run,target,
        ("Независимые тесты обнаружили повреждение функции." if detected
         else "Независимые тесты не доказали чувствительность к ошибке: "+
              str(report.output)[-450:])
    )

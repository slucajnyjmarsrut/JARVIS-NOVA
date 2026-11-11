# -*- coding: utf-8 -*-
"""Static engineering review of a proposed project; never executes a module."""
from __future__ import annotations

from dataclasses import dataclass
import ast

from code_workspace import ChangePlan, validate_plan


@dataclass(frozen=True)
class ReviewFinding:
    severity: str
    path: str
    line: int
    message: str


@dataclass(frozen=True)
class ProjectReview:
    findings: tuple[ReviewFinding, ...]
    test_files: int
    source_files: int

    @property
    def risk_count(self):
        return sum(item.severity == "risk" for item in self.findings)

    def summary(self):
        if self.risk_count:
            return "Есть опасные операции: требуется разбор вручную"
        if not self.test_files:
            return "Нет проверяемых тестов: функциональность не подтверждена"
        return "Статическая рецензия выполнена; функциональные тесты отдельно"


_RISK_CALLS = frozenset({
    "eval", "exec", "compile", "os.system", "os.popen",
    "subprocess.Popen", "pickle.loads", "pickle.load",
})
_RISK_MODULES = frozenset({"ctypes", "winreg"})


def review_change_plan(plan: ChangePlan, *, max_findings=40) -> ProjectReview:
    """Inspect code against common dangerous patterns; heuristic only."""
    validate_plan(plan)
    findings = []
    tests = 0
    sources = 0

    def add(level, path, line, message):
        if len(findings) < max_findings:
            findings.append(ReviewFinding(level, path, line, message))

    for item in plan.files:
        path = item.path
        if path.replace("\\", "/").split("/")[-1].startswith("test_"):
            tests += 1
        if not path.endswith(".py"):
            continue
        sources += 1
        try:
            tree = ast.parse(item.content, filename=path)
        except SyntaxError as exc:
            add("risk", path, exc.lineno or 0, "Python AST не проходит проверку")
            continue
        for node in ast.walk(tree):
            line = getattr(node, "lineno", 0)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in _RISK_MODULES:
                        add("risk", path, line, "Импорт низкоуровневого системного модуля")
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in _RISK_MODULES:
                    add("risk", path, line, "Импорт системного API")
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    add("warning", path, line, "Голый except скрывает системные ошибки")
                if (len(node.body) == 1 and
                        isinstance(node.body[0], ast.Pass)):
                    add("warning", path, line, "Ошибки молча игнорируются")
            if not isinstance(node, ast.Call):
                continue
            try:
                name = ast.unparse(node.func)
            except Exception:
                continue
            if name in _RISK_CALLS:
                add("risk", path, line,
                    "Проверь опасную операцию: " + name)
            if name.startswith("subprocess."):
                for kw in node.keywords:
                    if (kw.arg == "shell" and
                            not (isinstance(kw.value, ast.Constant)
                                 and kw.value.value is False)):
                        add("risk", path, line,
                            "subprocess с shell=True или динамическим shell")
            if name in ("yaml.load", "marshal.loads"):
                add("risk", path, line, "Потенциально небезопасная десериализация")
    if not tests:
        add("warning", "tests/", 0,
            "Нет файлов тестов: проверка синтаксиса не доказывает работу кода")
    if not any(item.path.lower().endswith(("readme.md", "readme.txt"))
               for item in plan.files):
        add("note", "README.md", 0,
            "Нет инструкции запуска или проверки проекта")
    return ProjectReview(tuple(findings), tests, sources)

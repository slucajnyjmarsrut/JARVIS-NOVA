# -*- coding: utf-8 -*-
"""Safety-first source validation: parse / compile only, NEVER run model code.

No dependency installs, package-manager builds, shell=True or generated
test execution. Compilation success is not a functional/integration test.
"""
from __future__ import annotations
import ast
import html.parser
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import tomllib
import xml.etree.ElementTree as ET
from code_workspace import WorkspaceError
from code_languages import EXTENSIONS, LANGUAGE_FILES, SUPPORTED

MAX_CHECK_FILES=100
MAX_ERRORS=6000
SAFE_SYNTAX_TOOLS={
    "javascript": (("node","--check"),{".js",".mjs",".cjs"}),
    "typescript": (("tsc","--noEmit","--skipLibCheck","--target","ES2020"),{".ts"}),
    "c": (("gcc","-fsyntax-only","-std=c11"),{".c"}),
    "cpp": (("g++","-fsyntax-only","-std=c++17"),{".cpp",".cc",".cxx"}),
    "go": (("gofmt","-e"),{".go"}),
    "rust": (("rustfmt","--emit","stdout"),{".rs"}),
    "php": (("php","-l"),{".php"}),
    "ruby": (("ruby","-c"),{".rb"}),
    "kotlin": (("kotlinc","-nowarn","-d"),{".kt"}),
    "swift": (("swiftc","-frontend","-parse"),{".swift"}),
    "dart": (("dart","analyze","--fatal-infos"),{".dart"}),
    "lua": (("luac","-p"),{".lua"}),
    "bash": (("bash","-n"),{".sh"}),
}
class _HTMLCheck(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags=0
    def handle_starttag(self, tag, attrs):
        self.tags+=1

def _static_check(path:Path) -> None:
    content=path.read_text(encoding="utf-8")
    if not content.strip():
        if path.name == "__init__.py":
            return
        raise ValueError("Пустой исходный файл")
    if "\x00" in content:
        raise ValueError("Недопустимый нуль в файле")
    if path.suffix in (".py",".pyi"):
        ast.parse(content, filename=path.name)
    elif path.suffix==".json":
        json.loads(content)
    elif path.suffix==".toml":
        tomllib.loads(content)
    elif path.suffix in (".xml",".csproj"):
        ET.fromstring(content)
    elif path.suffix==".html":
        html_parser=_HTMLCheck()
        html_parser.feed(content)
        html_parser.close()
    elif path.suffix==".css":
        if content.count("{")!=content.count("}"):
            raise ValueError("Несбалансированные фигурные скобки CSS")
    elif path.suffix==".sql":
        # sqlite3.complete_statement is ONLY a completeness check, not a
        # SQL validity proof and does not execute even a single statement.
        if not sqlite3.complete_statement(content.strip()+"\n"):
            raise ValueError("Неполный SQL: проверь точку с запятой")
    elif path.suffix==".svg":
        ET.fromstring(content)

def _syntax_process(cmd,root:Path,timeout=20):
    try:
        result=subprocess.run(cmd,cwd=str(root),shell=False,
            text=True,capture_output=True,timeout=timeout,
            stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return "Превышено время проверки"
    except OSError:
        return "Не удалось запустить установленный компилятор"
    if result.returncode:
        return (result.stderr+"\n"+result.stdout)[-MAX_ERRORS:] or "Ошибка проверки"
    return None

def check_project(language:str,root:Path,*,timeout=30)->dict:
    """Returns passed/partial/failed/skipped, clearly not a gameplay test."""
    if language not in SUPPORTED:
        raise WorkspaceError("Неизвестный язык проекта")
    if language=="java":
        from code_agent import check_java
        return check_java(root,timeout=timeout)
    if language=="luau":
        from code_agent import check_luau
        return check_luau(root)
    root=Path(root).resolve()
    if not root.is_dir():
        return {"status":"failed","reason":"Папка проекта не существует"}
    paths=sorted(p for p in root.rglob("*")
                 if p.is_file() and p.suffix.lower() in EXTENSIONS[language])
    if len(paths)>MAX_CHECK_FILES:
        raise WorkspaceError("Слишком много файлов для одной проверки")
    allowed_sources=LANGUAGE_FILES[language]
    sources=[p for p in paths if p.suffix.lower() in allowed_sources]
    if not sources:
        return {"status":"skipped","reason":"Нет исходных файлов"}
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise WorkspaceError("Недопустимый путь проекта")
        if path.stat().st_size>500_000:
            return {"status":"failed","reason":"Файл слишком большой: "+path.name}
        try:
            _static_check(path)
        except (SyntaxError,UnicodeError,ValueError,ET.ParseError) as exc:
            return {"status":"failed","reason":f"{path.name}: {str(exc)[:350]}"}
    # Python AST is a real syntax parser. Never execute user-generated modules.
    if language=="python":
        return {"status":"passed","reason":"Python AST: синтаксис корректен. Код НЕ запускался.",
                "files":len(sources),"verification":"syntax_only"}
    entry=SAFE_SYNTAX_TOOLS.get(language)
    if entry is None:
        return {"status":"partial","reason":
                "Статическая структура проверена; компилятор или runtime не запускались.",
                "files":len(sources),"verification":"structure_only"}
    prefix,exts=entry
    tool=shutil.which(prefix[0])
    if tool is None:
        return {"status":"partial","reason":f"Нет {prefix[0]}: проверена только структура файлов.",
                "files":len(sources),"verification":"structure_only"}
    with tempfile.TemporaryDirectory(prefix="jarvis-syntax-") as tmp:
        # Inputs are only direct filenames, never shell commands or model
        # instructions. Runtime dependencies are never installed.
        for source in sources:
            if source.suffix.lower() not in exts:
                continue
            if language=="kotlin":
                cmd=[tool,source.as_posix(),*prefix[1:],str(Path(tmp)/"classes")]
            else:
                cmd=[tool,*prefix[1:],str(source)]
            err=_syntax_process(cmd,root,timeout=timeout)
            if err:
                return {"status":"failed","reason":f"{source.name}: {err}",
                        "verification":"syntax_only"}
    return {"status":"partial","reason":
            f"Проверка синтаксиса инструментом {prefix[0]} прошла; запуск, тесты и зависимости НЕ проверены.",
            "files":len(sources),"verification":"syntax_only"}

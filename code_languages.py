# -*- coding: utf-8 -*-
"""Supported project targets, safe source extensions, and deterministic scaffolds.

These are languages JARVIS can *generate* projects for. A toolchain/compiler
is required to verify each language; coverage must not be confused with expert
model competence or successful execution. No untrusted generated code is run.
"""
from __future__ import annotations

COMMON = frozenset({
    ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".xml",
    ".properties", ".gitignore", ".editorconfig",
})
LANGUAGE_FILES = {
    "java": {".java", ".gradle"},
    "luau": {".lua", ".luau"},
    "python": {".py", ".pyi"},
    "javascript": {".js", ".mjs", ".cjs", ".jsx"},
    "typescript": {".ts", ".tsx", ".js", ".jsx"},
    "c": {".c", ".h"},
    "cpp": {".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx"},
    "csharp": {".cs", ".csproj", ".sln"},
    "go": {".go", ".mod", ".sum"},
    "rust": {".rs", ".lock"},
    "php": {".php"},
    "ruby": {".rb"},
    "kotlin": {".kt", ".kts", ".gradle"},
    "swift": {".swift"},
    "dart": {".dart"},
    "html": {".html", ".css", ".js", ".svg"},
    "css": {".css", ".html", ".svg"},
    "sql": {".sql"},
    "lua": {".lua"},
    "bash": {".sh"},
}
SUPPORTED = frozenset(LANGUAGE_FILES)
EXTENSIONS = {language: frozenset(extensions) | COMMON
              for language, extensions in LANGUAGE_FILES.items()}
LANGUAGE_LABELS = {
    "java":"Java", "luau":"Roblox Luau", "python":"Python",
    "javascript":"JavaScript", "typescript":"TypeScript",
    "c":"C", "cpp":"C++", "csharp":"C#",
    "go":"Go", "rust":"Rust", "php":"PHP", "ruby":"Ruby",
    "kotlin":"Kotlin", "swift":"Swift", "dart":"Dart",
    "html":"HTML", "css":"CSS", "sql":"SQL", "lua":"Lua", "bash":"Bash",
}
# Try not to accidentally route a casual mention of two languages to coding.
ALIASES = {
    "javascript":"javascript", "js":"javascript", "джаваскрипт":"javascript",
    "typescript":"typescript", "ts":"typescript", "тайпскрипт":"typescript",
    "python":"python", "питон":"python", "пайтон":"python",
    "java":"java", "джава":"java",
    "roblox":"luau", "роблокс":"luau", "luau":"luau",
    "lua":"lua",
    "c++":"cpp", "cpp":"cpp", "си++":"cpp", "плюсплюс":"cpp",
    "c#":"csharp", "csharp":"csharp", "си шарп":"csharp",
    "c":"c", "си":"c",
    "golang":"go", "go":"go", "го":"go",
    "rust":"rust", "раст":"rust",
    "php":"php", "пхп":"php", "ruby":"ruby", "руби":"ruby",
    "kotlin":"kotlin", "котлин":"kotlin", "swift":"swift", "свифт":"swift",
    "dart":"dart", "дарт":"dart", "html":"html", "css":"css",
    "sql":"sql", "postgresql":"sql", "sqlite":"sql",
    "bash":"bash", "shell":"bash",
}
# Minimal compilable templates without external downloads or startup scripts.
_TEMPLATES = {
    "python": [("src/{name}/__init__.py", ""),
               ("src/{name}/main.py", 'def main() -> None:\n    print("JARVIS NOVA: {name}")\n\nif __name__ == "__main__":\n    main()\n'),
               ("tests/test_main.py", 'import ast\nimport pathlib\n\n\ndef test_source_parses():\n    path = pathlib.Path(__file__).resolve().parents[1] / "src" / "{name}" / "main.py"\n    ast.parse(path.read_text(encoding="utf-8"))\n')],
    "javascript": [("src/main.js", 'function greet() {{\n  return "JARVIS NOVA: {name}";\n}}\nmodule.exports = {{ greet }};\n')],
    "typescript": [("src/main.ts", 'export function greet(): string {{\n  return "JARVIS NOVA: {name}";\n}}\n'),
                   ("tsconfig.json", '{"compilerOptions":{"strict":true,"target":"ES2020","module":"ESNext","outDir":"dist"},"include":["src"]}\n')],
    "c": [("src/main.c", '#include <stdio.h>\n\nint main(void) {{\n    puts("JARVIS NOVA: {name}");\n    return 0;\n}}\n')],
    "cpp": [("src/main.cpp", '#include <iostream>\n\nint main() {{\n    std::cout << "JARVIS NOVA: {name}" << std::endl;\n    return 0;\n}}\n')],
    "csharp": [("src/Program.cs", 'using System;\n\npublic static class Program {{\n    public static void Main() {{ Console.WriteLine("JARVIS NOVA: {name}"); }}\n}}\n')],
    "go": [("main.go", 'package main\n\nimport "fmt"\n\nfunc main() {{\n    fmt.Println("JARVIS NOVA: {name}")\n}}\n'),
           ("go.mod", "module example.com/{name}\n\ngo 1.21\n")],
    "rust": [("src/main.rs", 'fn main() {{\n    println!("JARVIS NOVA: {name}");\n}}\n'),
             ("Cargo.toml", '[package]\nname = "{name}"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\n')],
    "php": [("src/index.php", '<?php\nfunction greeting(): string {{\n    return "JARVIS NOVA: {name}";\n}}\necho greeting();\n')],
    "ruby": [("main.rb", 'def greeting\n  "JARVIS NOVA: {name}"\nend\n\nputs greeting\n')],
    "kotlin": [("src/Main.kt", 'fun main() {{\n    println("JARVIS NOVA: {name}")\n}}\n')],
    "swift": [("main.swift", 'print("JARVIS NOVA: {name}")\n')],
    "dart": [("bin/main.dart", "void main() {{\n  print('JARVIS NOVA: {name}');\n}}\n")],
    "html": [("index.html", '<!doctype html>\n<html lang="ru"><head><meta charset="utf-8"><title>{name}</title><link rel="stylesheet" href="style.css"></head><body><main><h1>{name}</h1></main></body></html>\n'),
             ("style.css", 'body {{ font-family: sans-serif; margin: 3rem; }}\n')],
    "css": [("index.html", '<!doctype html>\n<html lang="ru"><head><meta charset="utf-8"><link rel="stylesheet" href="style.css"><title>{name}</title></head><body><h1>{name}</h1></body></html>\n'),
            ("style.css", 'body {{ font-family: system-ui; margin: 3rem; }}\n')],
    "sql": [("schema.sql", 'CREATE TABLE IF NOT EXISTS items (\n    id INTEGER PRIMARY KEY,\n    title TEXT NOT NULL\n);\n')],
    "lua": [("main.lua", 'local function greeting()\n    return "JARVIS NOVA: {name}"\nend\nprint(greeting())\n')],
    "bash": [("main.sh", '#!/usr/bin/env bash\nset -euo pipefail\nprintf "%s\\n" "JARVIS NOVA: {name}"\n')],
}
def starter_files(language: str, name: str) -> tuple[tuple[str, str], ...]:
    if language not in _TEMPLATES:
        raise ValueError("Встроенный шаблон отсутствует")
    return tuple((path.replace("{name}",name),
                  content.replace("{name}",name).replace("{{","{").replace("}}","}"))
                 for path, content in _TEMPLATES[language])

# -*- coding: utf-8 -*-
"""REAL optional Qwen2.5-Coder:7b software-writing smoke (no Vision).

For runner security, untrusted model-written Python is NEVER executed on
the Windows host. Parses the full project, performs Python AST checks and
compares two simple mathematical function implementations against an
independent static contract. Real Docker execution and mutation testing are
covered by a SEPARATE CI job with a deterministic generator.
This is not a proof that Qwen can build arbitrary complex projects.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from task_ai_registry import LOOPBACK, get_specialist, specialist_available
from code_agent import request_local_model
from code_workspace import parse_model_proposal, WorkspaceError
from code_checks import check_project


def _assert_small_real_project(plan,workspace):
    if plan.language!="python":
        raise RuntimeError("Real Qwen returned another programming language.")
    files={entry.path:entry.content for entry in plan.files}
    if "README.md" not in files or len(files["README.md"].strip())<40:
        raise RuntimeError("No meaningful README from real Qwen.")
    modules=[(path,source) for path,source in files.items()
             if path.endswith(".py") and not path.startswith("tests/")]
    tests=[(path,source) for path,source in files.items()
           if path.startswith("tests/test_") and path.endswith(".py")]
    if not modules or not tests or len(files)<3:
        raise RuntimeError("Qwen did not create Python code + tests + README.")
    functions={}
    for path,source in modules:
        tree=ast.parse(source,filename=path)
        for node in tree.body:
            if isinstance(node,ast.FunctionDef):
                functions[node.name]=node
    for name,operator in (("add",ast.Add),("subtract",ast.Sub)):
        fn=functions.get(name)
        if fn is None or len(fn.args.args)!=2:
            raise RuntimeError("Missing public two-argument function: "+name)
        returns=[node for node in ast.walk(fn)
                 if isinstance(node,ast.Return)]
        if not any(isinstance(node.value,ast.BinOp) and
                   isinstance(node.value.op,operator) and
                   isinstance(node.value.left,ast.Name) and
                   isinstance(node.value.right,ast.Name)
                   for node in returns):
            raise RuntimeError(
                f"The real Qwen {name} algorithm did not match basic static contract.")
    cases=0
    for path,code in tests:
        tree=ast.parse(code,filename=path)
        for cls in tree.body:
            if not isinstance(cls,ast.ClassDef):
                continue
            for node in cls.body:
                if isinstance(node,ast.FunctionDef) and node.name.startswith("test_"):
                    if any(isinstance(child,ast.Call) and
                           isinstance(child.func,ast.Attribute) and
                           child.func.attr.startswith("assert")
                           for child in ast.walk(node)):
                        cases+=1
    if cases<2:
        raise RuntimeError("Model-written project lacks two real assertions.")
    for path,code in files.items():
        target=workspace/path
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            raise RuntimeError("Generated project unexpectedly overwrote a file.")
        target.write_text(code,encoding="utf-8")
    report=check_project("python",workspace)
    if report["status"]!="passed" or report.get("verification")!="syntax_only":
        raise RuntimeError("Qwen code is not syntactically valid: "+repr(report))
    return len(files),cases


def main() -> int:
    for out in (sys.stdout,sys.stderr):
        if out is not None and hasattr(out,"reconfigure"):
            out.reconfigure(encoding="utf-8",errors="backslashreplace")
    topic=(
        "Build a small COMPLETE Python project with exactly these files: "
        "calculator.py, tests/test_calculator.py, README.md. "
        "calculator.py MUST export two independent functions: "
        "def add(a,b): return a+b and def subtract(a,b): return a-b. "
        "Test code MUST have unittest.TestCase with at least TWO test_* "
        "methods asserting numeric results for positive and negative inputs. "
        "README must have at least 40 characters explaining the project. "
        "Use only the Python standard library. All files are REAL content "
        "with correct Python syntax; no placeholders, markdown fences or "
        "fake output. JSON schema must be exactly language/files. "
        "No operating-system actions or network access. Each file <150 lines."
    )
    try:
        spec=get_specialist("code")
        if not specialist_available("code"):
            print("REAL CODER NOT RUN: dedicated "+spec.model+
                  " is unavailable. Start Ollama and approve model download "
                  "separately before retrying.",file=sys.stderr,flush=True)
            return 2
        failures=[]
        for attempt in range(1,4):
            try:
                raw=request_local_model(
                    topic,"python",endpoint=LOOPBACK,
                    model=spec.model)
                plan=parse_model_proposal(raw)
                with tempfile.TemporaryDirectory(
                    prefix="nova-real-qwen-code-") as tmp:
                    count,cases=_assert_small_real_project(plan,Path(tmp))
                print(
                    "REAL QWEN CODER PASS: "+str(attempt)+" attempts; "+
                    str(count)+" real generated files, "+str(cases)+
                    " model-written test cases, independent AST semantics "
                    "and syntax passed; UNTRUSTED CODE WAS NOT EXECUTED.",
                    flush=True)
                return 0
            except (ValueError,TypeError,SyntaxError,WorkspaceError,
                    RuntimeError) as exc:
                failures.append(type(exc).__name__+": "+str(exc)[:240])
                topic=(topic+"\nLast draft rejected: "+str(exc)[:240]
                       +". Fix output and return complete files.")
        raise RuntimeError(
            "Qwen could not meet even the bounded Python smoke contract: "+
            " | ".join(failures)[-800:])
    except Exception as exc:
        print("REAL QWEN CODER FAILED: "+
              type(exc).__name__+": "+str(exc),
              file=sys.stderr,flush=True)
        return 1



if __name__=="__main__":
    raise SystemExit(main())

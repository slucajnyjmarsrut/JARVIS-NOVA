import tempfile
import unittest
from pathlib import Path
from code_workspace import (WorkspaceError, ChangePlan, ProposedFile, starter_project,
                            apply_plan, preview, parse_model_proposal)

class WorkspaceTests(unittest.TestCase):
    def test_model_double_escaped_lines_become_real_python_only_if_valid(self):
        import ast
        import json
        raw=json.dumps({"language":"python","files":[{
            "path":"calculator.py",
            "content":r"def add(a,b):\n    return a+b\n"}]})
        project=parse_model_proposal(raw)
        code=project.files[0].content
        self.assertEqual(code,"def add(a,b):\n    return a+b\n")
        ast.parse(code)

    def test_legitimate_escape_sequences_never_rewritten(self):
        import json
        code=r"LINE = '\\n'"
        raw=json.dumps({"language":"python","files":[{
            "path":"values.py","content":code}]})
        self.assertEqual(
            parse_model_proposal(raw).files[0].content,code)

    def test_nonrepairable_code_keeps_original_error_for_reprompting(self):
        import json
        code=r"def greet():\n    return 'broken\ntext'"
        raw=json.dumps({"language":"python","files":[{
            "path":"broken.py","content":code}]})
        self.assertEqual(
            parse_model_proposal(raw).files[0].content,code)

    def test_java(self):
        with tempfile.TemporaryDirectory() as d:
            p = starter_project('java', 'Demo')
            self.assertEqual(len(apply_plan(p, Path(d), confirmed=True)), 2)
            self.assertIn('public static void main', (Path(d)/'src/main/java/Demo/Main.java').read_text())
    def test_luau(self):
        with tempfile.TemporaryDirectory() as d:
            p = starter_project('luau', 'Game')
            self.assertEqual(preview(p, Path(d))[0]['action'], 'create')
            apply_plan(p, Path(d), confirmed=True)
            self.assertTrue((Path(d)/'src/server/Main.server.luau').exists())
    def test_approval_required(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(PermissionError): apply_plan(starter_project('java','Demo'),Path(d))
    def test_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=starter_project('java','Demo')
            apply_plan(p,Path(d),confirmed=True)
            with self.assertRaises(WorkspaceError): apply_plan(p,Path(d),confirmed=True)
    def test_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('../evil.java', '/tmp/evil.java', 'src/../../evil.java', 'C:/evil.java'):
                with self.subTest(name=name), self.assertRaises(WorkspaceError):
                    preview(ChangePlan('java',(ProposedFile(name,'bad'),)),Path(d))
    def test_windows_reserved_names(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('CON.java','dir/AUX.java','dir/COM1.java','LPT9.java'):
                with self.subTest(name=name),self.assertRaises(WorkspaceError):
                    preview(ChangePlan('java',(ProposedFile(name,'class X {}'),)),Path(d))
    def test_bad_extension(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(WorkspaceError):
                preview(ChangePlan('java',(ProposedFile('run.bat','echo hi'),)),Path(d))
    def test_model_schema(self):
        self.assertEqual(parse_model_proposal('{"language":"luau","files":[{"path":"Main.luau","content":"print(1)"}]}').language,'luau')
        with self.assertRaises(WorkspaceError): parse_model_proposal('{"language":"java","files":[],"command":"rm -rf"}')
    def test_symlink(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            (Path(d)/'src').symlink_to(Path(outside),target_is_directory=True)
            with self.assertRaises(WorkspaceError):
                preview(ChangePlan('java',(ProposedFile('src/Test.java','hi'),)),Path(d))

if __name__ == '__main__': unittest.main()

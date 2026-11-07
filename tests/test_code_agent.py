import json
import tempfile
import unittest
from pathlib import Path
from code_agent import request_local_model, propose, approve_and_write, check_java, check_luau
from code_workspace import WorkspaceError

class AgentTests(unittest.TestCase):
    def test_local_endpoint_only(self):
        with self.assertRaises(WorkspaceError):
            request_local_model('Make a class', 'java', endpoint='https://example.com')
    def test_request_schema(self):
        def fake(url, payload):
            self.assertEqual(url, 'http://127.0.0.1:11434/api/chat')
            self.assertEqual(payload['format'], 'json')
            return {'message': {'content': '{"language":"java","files":[{"path":"Main.java","content":"class Main {}"}]}'}}
        self.assertIn('Main.java', request_local_model('Create Java', 'java', transport=fake))
    def test_propose_requires_approval(self):
        with tempfile.TemporaryDirectory() as d:
            result = propose('make Java', 'java', Path(d), generator=lambda task, language: json.dumps({
                'language': 'java', 'files': [{'path': 'Main.java', 'content': 'class Main {}'}]}))
            with self.assertRaises(PermissionError): approve_and_write(result, Path(d))
            self.assertFalse((Path(d)/'Main.java').exists())
            approve_and_write(result, Path(d), approved=True)
            self.assertTrue((Path(d)/'Main.java').exists())
    def test_language_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(WorkspaceError):
                propose('make Java', 'java', Path(d), generator=lambda t,l: '{"language":"luau","files":[{"path":"Main.luau","content":"print(1)"}]}')
    def test_luau_static(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'Main.luau').write_text('print("Hello")')
            self.assertEqual(check_luau(Path(d))['status'], 'partial')
    def test_java_compilation_or_skip(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'Main.java').write_text('public class Main {}')
            self.assertIn(check_java(Path(d))['status'], ('passed','skipped'))

if __name__ == '__main__': unittest.main()

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
    def test_model_name_is_bounded_and_no_unsafe_endpoint(self):
        for name in ("", "model name with spaces", "../outside",
                     "qwen" * 100, "model\\nsecret"):
            with self.subTest(name=name),self.assertRaises(WorkspaceError):
                request_local_model(
                    "Create safe code","java",model=name,
                    transport=lambda *a:self.fail("No model call"))

    def test_default_ollama_transport_rejects_all_redirects(self):
        from unittest import mock
        from io import BytesIO
        import urllib.request
        from code_agent import _RejectModelRedirect
        content=json.dumps({"message":{"content":"{}"}}).encode("utf-8")
        class FakeOpener:
            def open(self,request,timeout=None):
                self_outer.assertEqual(timeout,180)
                self_outer.assertEqual(request.full_url,
                                       "http://127.0.0.1:11434/api/chat")
                return BytesIO(content)
        self_outer=self
        with mock.patch("code_agent.urllib.request.build_opener",
                        return_value=FakeOpener()) as builder:
            request_local_model("Generate a project","java")
            handlers=builder.call_args.args
            self.assertTrue(any(isinstance(h,_RejectModelRedirect)
                                for h in handlers))
            reject=next(h for h in handlers if
                        isinstance(h,_RejectModelRedirect))
            for target in ("https://example.com/leak",
                           "http://127.0.0.1:9000/api/sink"):
                with self.assertRaises(WorkspaceError):
                    reject.redirect_request(
                        None,None,302,"Moved",{},target)

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

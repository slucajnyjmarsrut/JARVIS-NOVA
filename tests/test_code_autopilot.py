import json
import tempfile
import unittest
from pathlib import Path
from code_autopilot import generate_and_check, install_reviewed

def proposal(code):
    return json.dumps({'language':'java','files':[{'path':'Main.java','content':code}]})

class AutopilotTests(unittest.TestCase):
    def test_repairs_compile_failure(self):
        calls=[]
        def generator(task,language):
            calls.append(task)
            return proposal('class Main { syntax error }') if len(calls)==1 else proposal('class Main {}')
        result=generate_and_check('Write Main', 'java',generator=generator)
        self.assertEqual([a.status for a in result.attempts],['failed','passed'])
        self.assertTrue(result.verified)
    def test_does_not_write_before_confirmation(self):
        result=generate_and_check('Write Main','java',generator=lambda *_:proposal('class Main {}'))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(PermissionError):install_reviewed(result,Path(d))
            self.assertEqual(list(Path(d).iterdir()),[])
            install_reviewed(result,Path(d),confirmed=True)
            self.assertTrue((Path(d)/'Main.java').exists())
            with self.assertRaises(ValueError):install_reviewed(result,Path(d),confirmed=True)
    def test_failure_does_not_write(self):
        result=generate_and_check('Broken','java',generator=lambda *_:proposal('class Main { nope }'),max_attempts=2)
        self.assertFalse(result.verified)
        self.assertEqual(len(result.attempts),2)
    def test_luau_is_not_claimed_verified(self):
        raw=json.dumps({'language':'luau','files':[{'path':'src/server/Main.server.luau','content':'print("ok")'}]})
        result=generate_and_check('Hi','luau',generator=lambda *_:raw)
        self.assertFalse(result.verified)
        self.assertEqual(result.attempts[0].status,'partial')

if __name__=='__main__':unittest.main()

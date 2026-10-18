# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_core import parse_local,validate_plan,Step,Plan,ask_ai_for_plan
from voice_engine import Voice
from desktop import Desktop

class PlanTests(unittest.TestCase):
    def test_apps_and_chrome(self):
        p=parse_local("Джарвис, открой хром")
        self.assertEqual(p.steps,[Step("open_app","Google Chrome")])
    def test_sequence(self):
        p=parse_local("Джарвис, открой Chrome и увеличь масштаб")
        self.assertEqual([s.kind for s in p.steps],["open_app","zoom_in"])
    def test_negation(self):
        self.assertEqual(parse_local("не открывай Chrome").steps,[])
    def test_unsafe_executable(self):
        self.assertEqual(parse_local("открой powershell").steps,[])
    def test_incomplete(self):
        self.assertTrue(parse_local("открой").question)
    def test_vision_routing(self):
        self.assertEqual(parse_local("что ты видишь").steps,[Step("screen_describe")])
    def test_close_requires_confirmation(self):
        self.assertTrue(validate_plan(parse_local("закрой окно")).need_confirmation)
    def test_click_requires_confirmation(self):
        self.assertTrue(validate_plan(parse_local("нажми 300 450")).need_confirmation)
    def test_url_scheme(self):
        with self.assertRaises(ValueError):
            validate_plan(Plan(steps=[Step("open_url","http://example.org")]))
    def test_reject_ai_shell(self):
        with self.assertRaises(ValueError):
            validate_plan(Plan(steps=[Step("run_shell","rm -rf /")]))
    def test_too_many(self):
        with self.assertRaises(ValueError):
            validate_plan(Plan(steps=[Step("zoom_in")]*4))
    def test_hotkey_whitelist(self):
        with self.assertRaises(ValueError):
            validate_plan(Plan(steps=[Step("hotkey","win+r")]))
    def test_open_question(self):
        self.assertTrue(parse_local("напиши").question)
    def test_voice_no_wake(self):
        heard=[]
        v=Voice(heard.append,lambda s:None,lambda:False)
        v.accept_text("открой Chrome")
        self.assertEqual(heard,[])
    def test_voice_wake_fragment_and_followup(self):
        heard=[]
        v=Voice(heard.append,lambda s:None,lambda:False)
        v.accept_text("джарвис")
        v.accept_text("открой")
        v.accept_text("хром")
        self.assertEqual(heard,["открой хром"])
    def test_voice_wake_single(self):
        heard=[]
        v=Voice(heard.append,lambda s:None,lambda:False)
        v.accept_text("жарвис открой Chrome")
        self.assertEqual(heard,["открой Chrome"])
    def test_no_execute_during_tts(self):
        heard=[]
        v=Voice(heard.append,lambda s:None,lambda:True)
        v.accept_text("джарвис открой Chrome")
        self.assertEqual(heard,[])
    def test_ai_rejects_arbitrary_shell_plan(self):
        answer={"message":{"content":'{"steps":[{"kind":"run_shell","value":"rm -rf /"}]}' }}
        with mock.patch("agent_core.request_json",return_value=answer):
            p=ask_ai_for_plan("запусти команду",engine="ollama")
        self.assertFalse(p.steps)
        self.assertIn("ai недоступен",p.question.casefold())

    def test_ai_plan_needs_confirmation(self):
        answer={"message":{"content":'{"steps":[{"kind":"open_app","value":"Google Chrome"}]}' }}
        with mock.patch("agent_core.request_json",return_value=answer):
            p=ask_ai_for_plan("открой Chrome",engine="ollama")
        self.assertEqual(p.steps[0].kind,"open_app")
        self.assertTrue(p.need_confirmation)

    def test_open_app_blocked_without_shortcuts(self):
        d=Desktop()
        with mock.patch.object(d,"shortcuts",return_value=[]):
            with self.assertRaises(FileNotFoundError):
                d.open_app("nonexistent-app-111")
    def test_control_permission_required(self):
        d=Desktop(lambda:False)
        with self.assertRaises(PermissionError):
            d.run(Step("click",x=100,y=100))
    def test_vision_permission_required(self):
        d=Desktop(lambda:False,lambda:False)
        with self.assertRaises(PermissionError):
            d.run(Step("screen_describe"))

if __name__=="__main__":unittest.main()

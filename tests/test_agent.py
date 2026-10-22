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
    def test_every_executable_alias_and_system_shell_is_denied(self):
        names=("powershell.exe","cmd.exe","pwsh","rundll32","mshta",
               "wscript","cscript","taskkill","regedit.exe","shutdown",
               "taskmgr","windows terminal","командная строка")
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(parse_local("Джарвис, открой "+name).steps,[])
                with self.assertRaises(ValueError):
                    validate_plan(Plan(steps=[Step("open_app",name)]))
        with self.assertRaises(ValueError):
            validate_plan(Plan(steps=[Step("open_app","C:\\Windows\\System32\\cmd.exe")]))
        self.assertEqual(parse_local("открой C:\\Windows\\System32\\cmd.exe").steps,[])

    def test_local_planner_defaults_to_actually_bundled_model(self):
        def requester(url,payload,*args,**kwargs):
            self.assertEqual(payload["model"],"qwen3-vl:2b-instruct")
            return {"message":{"content":'{"steps":[]}'}}
        with mock.patch("agent_core.request_json",side_effect=requester):
            self.assertFalse(ask_ai_for_plan("что открыто",engine="ollama").steps)

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
    def test_spoken_url_keeps_case_sensitive_path_and_query(self):
        address="https://Example.COM/CaseSensitive/SignIn?Token=AbC123&Mode=Fast"
        plan=parse_local("Джарвис, открой "+address)
        self.assertEqual(plan.steps,[Step("open_url",address)])
        validate_plan(plan)
        d=Desktop()
        with mock.patch("desktop.webbrowser.open",return_value=True) as browser:
            d.run(plan.steps[0])
        browser.assert_called_once_with(address)
        upper=parse_local("Джарвис, открой HTTPS://Example.org/Path?Secret=XYZ")
        self.assertEqual(upper.steps,[Step("open_url","https://Example.org/Path?Secret=XYZ")])
        validate_plan(upper)

    def test_reject_malformed_local_or_credentialed_https(self):
        blocked=(
            "https://", "https://localhost/admin", "https://localhost.localdomain/",
            "https://intranet.local/config", "https://device.internal/",
            "https://192.168.0.1/", "https://127.0.0.1:443/",
            "https://[::1]/", "https://10.0.0.2/path",
            "https://user:password@example.org/",
            "https://example.org:4443/", "https://example.org:bad/",
            "https://example..org/", "https://-example.org/",
            "https://example-.org/", "https://example.1/",
            "https://evil.example.com@localhost/admin", "https://bad%2Fexample.org/",
            "https://example.org\evil", "https://example.org/a b",
            "https://example.org/a\ninjected", "https://example.org/\tinjected",
            "https:///no-host", "https://example.org:65536/",
            "https://[::1", "https://server.invalid/",
            "https://example.org\\@internal.invalid/",
            "http://example.org/",
        )
        for value in blocked:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    validate_plan(Plan(steps=[Step("open_url",value)]))
                d=Desktop()
                with mock.patch("desktop.webbrowser.open") as browser:
                    with self.assertRaises(ValueError):
                        d.run(Step("open_url",value))
                    browser.assert_not_called()

    def test_unsafe_spoken_browser_links_yield_question_not_desktop_action(self):
        for url in ("https://localhost/admin","https://127.0.0.1:443/",
                    "https://example.org:bad","http://example.org/"):
            with self.subTest(url=url):
                plan=parse_local("Джарвис открой "+url)
                self.assertEqual(plan.steps,[])
                self.assertIn("HTTPS",plan.question)

    def test_public_links_remain_usable(self):
        for address in (
            "https://example.org/", "https://commons.wikimedia.org/wiki/File:Example",
            "https://www.youtube.com/watch?v=AbCdE_99",
            "https://1.1.1.1/dns-query", "https://example.com:443/path#fragment",
            "https://пример.рф/Путь?Ключ=АБВ",
        ):
            with self.subTest(address=address):
                validate_plan(Plan(steps=[Step("open_url",address)]))

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
    def test_legacy_screen_description_uses_bundled_model_and_loopback(self):
        from PIL import Image
        picture=Image.new("RGB",(16,16),(120,40,80))
        seen=[]
        def requester(endpoint,payload,**kwargs):
            seen.append((endpoint,payload))
            self.assertEqual(payload["model"],"qwen3-vl:2b-instruct")
            self.assertTrue(payload["images"][0])
            self.assertEqual(endpoint,"http://127.0.0.1:11434/api/generate")
            return {"response":"На экране тестовая картинка."}
        d=Desktop(lambda:False,lambda:True)
        with mock.patch.dict("desktop.os.environ",{},clear=True), \
             mock.patch("PIL.ImageGrab.grab",return_value=picture), \
             mock.patch("desktop.request_json",side_effect=requester):
            result=d.describe_screen()
        self.assertIn("тестовая",result)
        self.assertEqual(len(seen),1)

    def test_control_permission_required(self):
        d=Desktop(lambda:False)
        with self.assertRaises(PermissionError):
            d.run(Step("click",x=100,y=100))
    def test_vision_permission_required(self):
        d=Desktop(lambda:False,lambda:False)
        with self.assertRaises(PermissionError):
            d.run(Step("screen_describe"))

if __name__=="__main__":unittest.main()

# -*- coding: utf-8 -*-
import json
import pathlib
import tempfile
import unittest
from unittest.mock import Mock, patch
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from work_modes import ModeManager, MODES, VIDEO_STAGES
from main import Jarvis


class ModesTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=pathlib.Path(self.tmp.name)/'modes.json'
        self.manager=ModeManager(self.path)
        self.installed={'Notepad','Calculator','Explorer','Steam','Discord','Google Chrome'}
        self.check=lambda name: name in self.installed

    def test_four_distinct_mode_commands(self):
        for phrase,mode in [('Джарвис, включи игровой режим','gaming'),
                            ('перейди в рабочий режим','work'),
                            ('включи офисный режим','office'),
                            ('включи учебный режим','study')]:
            with self.subTest(phrase=phrase):
                result=self.manager.parse(phrase,self.check)
                self.assertEqual(result.kind,'game_prompt' if mode=='gaming' else 'switch')
                self.assertEqual(self.manager.mode,mode)

    def test_neutral_does_not_run_programs(self):
        self.manager.parse('включи учебный режим',self.check)
        result=self.manager.parse('обычный режим',self.check)
        self.assertEqual(result.kind,'switch')
        self.assertIsNone(result.plan)
        self.assertEqual(self.manager.mode,'neutral')

    def test_game_mode_asks_before_launch(self):
        intro=self.manager.parse('включи игровой режим',self.check)
        self.assertEqual(intro.kind,'game_prompt')
        self.assertTrue(self.manager.awaiting_game)
        self.assertFalse(self.manager.game_name)
        self.assertIsNone(intro.plan)
        self.assertEqual(self.manager.parse('начни игровой сеанс',self.check).kind,'game_prompt')
        selected=self.manager.parse('Portal 2',self.check)
        self.assertEqual(selected.kind,'game_launch')
        self.assertEqual(selected.game,'portal 2')
        self.assertIsNone(selected.plan)
        self.assertEqual(self.manager.parse('начни сессию',self.check).game,'portal 2')

    def test_office_runs_three_safe_actions(self):
        self.manager.parse('включи офисный режим',self.check)
        result=self.manager.parse('офисный старт',self.check)
        self.assertEqual(len(result.plan.steps),3)
        self.assertTrue(all(s.kind=='open_app' for s in result.plan.steps))

    def test_office_specific_command(self):
        self.manager.parse('включи офисный режим',self.check)
        result=self.manager.parse('открой рабочие файлы',self.check)
        self.assertEqual(result.plan.steps[0].value,'Explorer')

    def test_study_commands_different_from_games(self):
        self.manager.parse('включи учебный режим',self.check)
        result=self.manager.parse('начни занятие',self.check)
        self.assertEqual([s.value for s in result.plan.steps],['Notepad','Calculator'])
        self.assertIsNone(self.manager.parse('начни игровой сеанс',self.check))

    def test_work_apps_skipped_without_auto_launch(self):
        self.installed.remove('Google Chrome')
        self.manager.parse('включи рабочий режим',self.check)
        result=self.manager.parse('начни сессию',self.check)
        self.assertEqual([s.value for s in result.plan.steps],['Notepad'])
        self.assertIn('Пропущены',result.message)

    def test_missing_apps_gives_message(self):
        self.installed.clear()
        self.manager.parse('включи рабочий режим',self.check)
        result=self.manager.parse('начни сессию',self.check)
        self.assertEqual(result.kind,'message')
        self.assertIsNone(result.plan)

    def test_typical_voice_commands_not_hijacked(self):
        self.manager.parse('включи рабочий режим',self.check)
        for phrase in ('открой Chrome','отмена','Джарвис посмотри на экран',
                       'не включай игровой режим','отключи интернет'):
            with self.subTest(phrase=phrase):
                self.assertIsNone(self.manager.parse(phrase,self.check))
        self.assertEqual(self.manager.mode,'work')

    def test_focus_timer_scope(self):
        self.assertIn('доступен',self.manager.parse('помодоро',self.check).message)
        self.manager.parse('включи учебный режим',self.check)
        self.assertEqual(self.manager.parse('начни помодоро',self.check).minutes,25)
        self.assertEqual(self.manager.parse('таймер 15 минут',self.check).minutes,15)
        self.assertEqual(self.manager.parse('таймер 400 минут',self.check).kind,'message')
        self.assertEqual(self.manager.parse('останови таймер',self.check).kind,'timer_stop')
        self.assertEqual(self.manager.parse('сколько осталось',self.check).kind,'timer_status')

    def test_configuration_is_app_names_only(self):
        invalid=[['notepad.exe /c whoami'],['C:\\Windows\\system32\\cmd.exe'],
                 ['https://evil.example'],['powershell'],['Notepad','Notepad'],[]]
        for apps in invalid:
            with self.subTest(apps=apps),self.assertRaises(ValueError):
                self.manager.configure('work',apps,lambda _:True)
        self.assertFalse(self.path.exists())

    def test_uninstalled_app_rejected_without_save(self):
        with self.assertRaises(ValueError):
            self.manager.configure('gaming',['Notepad','Unknown app'],self.check)
        self.assertFalse(self.path.exists())

    def test_persistence_across_restart_not_mode(self):
        self.manager.parse('включи рабочий режим',self.check)
        self.manager.configure('work',['Notepad','Calculator'],self.check)
        again=ModeManager(self.path)
        self.assertEqual(again.mode,'neutral')
        self.assertEqual(again.apps('work'),('Notepad','Calculator'))
        again.parse('включи рабочий режим',self.check)
        self.assertEqual([s.value for s in again.parse('начни сессию',self.check).plan.steps],
                         ['Notepad','Calculator'])

    def test_tampered_json_does_not_inject_shell(self):
        self.path.write_text(json.dumps({'version':1,'apps':{'work':['cmd.exe /c echo hack']}},
                                        ensure_ascii=False),encoding='utf-8')
        other=ModeManager(self.path)
        self.assertEqual(other.apps('work'),MODES['work'].defaults)

    def test_truncated_json_not_brick_app(self):
        self.path.write_text('not json',encoding='utf-8')
        other=ModeManager(self.path)
        self.assertEqual(other.mode,'neutral')

    def test_mode_voice_routing_preempts_normal_agent(self):
        ui=Mock()
        ui._closing=False
        ui.desktop.is_installed=self.check
        ui.modes=self.manager
        ui.log=Mock()
        ui.handle_mode_command=Mock()
        self.manager.parse('включи игровой режим',self.check)
        Jarvis.handle_text(ui,'начни сессию')
        self.assertEqual(ui.handle_mode_command.call_args[0][0].kind,'game_prompt')
        self.assertFalse(ui.voice.vision_source.called)

    def test_timer_runs_and_announces_finish_only_once(self):
        ui=Mock()
        ui._closing=False
        ui._focus_epoch=0
        ui._focus_deadline=None
        ui.modes.mode='study'
        with patch('main.time.monotonic',return_value=100.0):
            Jarvis.start_focus_timer(ui,1)
        self.assertEqual(ui._focus_deadline,160.0)
        self.assertEqual(ui.after.call_count,1)
        # At deadline the timer announces once and clears itself.
        with patch('main.time.monotonic',return_value=161.0):
            Jarvis._focus_tick(ui,1)
        self.assertIsNone(ui._focus_deadline)
        self.assertIn('завершилась',ui.reply.call_args[0][0])

    def test_timer_old_epoch_does_not_fire_after_reset(self):
        ui=Mock()
        ui._closing=False
        ui._focus_epoch=2
        ui._focus_deadline=400.0
        Jarvis._focus_tick(ui,1)
        ui.after.assert_not_called()
        ui.reply.assert_not_called()

    def test_timer_is_cancelled_on_close(self):
        source=pathlib.Path(__file__).resolve().parents[1].joinpath('main.py').read_text('utf-8')
        self.assertIn('self._focus_deadline=None',source)
        self.assertIn('self._focus_epoch+=1',source)

if __name__=='__main__':unittest.main()

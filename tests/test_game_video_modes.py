# -*- coding: utf-8 -*-
import pathlib, sys, tempfile, unittest
from unittest.mock import Mock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from game_catalog import GameCatalog
from work_modes import ModeManager, VIDEO_STAGES
from main import Jarvis

class GameVideoModesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.manager=ModeManager(pathlib.Path(self.tmp.name)/'modes.json')
        self.installed=lambda _:True

    def test_all_video_modes_open_different_stages(self):
        pairs=[('включи режим роликов','videos','audience'),
               ('включи режим съемки','video_shoot','shoot'),
               ('режим монтажа','video_edit','edit'),
               ('включи режим оценки','video_review','review')]
        for phrase,key,stage in pairs:
            with self.subTest(phrase=phrase):
                result=self.manager.parse(phrase,self.installed)
                self.assertEqual(result.kind,'video_stage')
                self.assertEqual(self.manager.mode,key)
                self.assertEqual(result.stage,stage)
                self.assertIsNone(result.plan)

    def test_video_voice_route_respects_required_audience_step(self):
        self.manager.set_mode('video_edit')
        result=self.manager.parse('проанализируй канал',self.installed)
        self.assertEqual(result.stage,'audience')
        self.assertEqual(result.action,'audience')
        result=self.manager.parse('смонтируй ролик',self.installed)
        self.assertEqual(result.stage,'edit')
        self.assertEqual(result.action,'edit')
        self.assertIsNone(result.plan)

    def test_video_never_launches_apps_on_session(self):
        self.manager.set_mode('videos')
        r=self.manager.parse('начни сессию',self.installed)
        self.assertEqual(r.kind,'video_stage')
        self.assertIsNone(r.plan)

    def test_video_explicit_request_runs_existing_stage_with_confirmation(self):
        ui=Mock()
        ui._selected_mode=Mock()
        self.manager.set_mode('video_edit')
        command=self.manager.parse('смонтируй ролик',self.installed)
        ui.open_viral_studio.return_value=Mock()
        Jarvis.handle_mode_command(ui,command)
        ui.after.assert_called_once()
        args=ui.after.call_args[0]
        self.assertEqual(args[0],40)
        self.assertEqual(args[1],ui.open_viral_studio.return_value.montage)

    def test_game_cancel_and_mode_change(self):
        self.manager.set_mode('gaming')
        self.assertEqual(self.manager.parse('игра Minecraft',self.installed).kind,'game_launch')
        self.manager.set_mode('neutral')
        self.assertEqual(self.manager.game_name,'')
        self.assertFalse(self.manager.awaiting_game)

    def test_game_rejects_unsafe_name(self):
        self.manager.set_mode('gaming')
        for name in ('cmd.exe /c del C:', 'https://bad.example','C:\\Windows\\cmd.exe'):
            self.assertEqual(self.manager.choose_game(name).kind,'game_prompt')

    def test_ui_routes_video_without_implicit_upload(self):
        ui=Mock()
        ui._selected_mode=Mock()
        Jarvis.handle_mode_command(ui,self.manager.set_mode('videos'))
        ui.open_viral_studio.assert_called_once_with(stage='audience')
        self.assertFalse(ui.execute_plan.called)

    def test_steam_metadata_and_revalidation(self):
        base=pathlib.Path(self.tmp.name)/'Steam'
        folder=base/'steamapps';folder.mkdir(parents=True)
        (folder/'appmanifest_620.acf').write_text('"AppState"\n{\n"appid" "620"\n"name" "Portal 2"\n}',encoding='utf-8')
        catalog=GameCatalog((base,))
        self.assertIsNone(catalog.find('портал 2',[]))
        found=catalog.find('portal 2',[])
        self.assertIsNotNone(found)
        self.assertEqual(found.source,'steam')
        self.assertEqual(found.target,'620')
        self.assertTrue(catalog.validate_steam(found))
        (folder/'appmanifest_620.acf').unlink()
        self.assertFalse(catalog.validate_steam(found))

    def test_steam_rejects_untrusted_manifest_file(self):
        base=pathlib.Path(self.tmp.name)/'Steam';folder=base/'steamapps';folder.mkdir(parents=True)
        (folder/'appmanifest_a&del.acf').write_text('"name" "Trick game"')
        (folder/'appmanifest_99.acf').write_text('"name" "cmd.exe /c del"')
        self.assertEqual(GameCatalog((base,)).available(()),())

    def test_game_larger_session_does_not_execute_unverified_path(self):
        mock=Mock()
        mock.games.find.return_value=None
        mock.desktop.installed_names.return_value=[]
        mock.modes=Mock()
        Jarvis._launch_selected_game(mock,'not installed')
        mock.reply.assert_called_once()
        mock.execute_plan.assert_not_called()

if __name__=='__main__':unittest.main()

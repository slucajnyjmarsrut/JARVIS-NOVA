# -*- coding: utf-8 -*-
"""Safety invariant: JARVIS reveals an item; the owner deletes it manually."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_core import ask_ai_for_plan, parse_local
from chat_first_intent import route_chat_request, ChatIntent
from main import Jarvis
from manual_file_deletion import (
    choose_for_manual_deletion, is_delete_request, is_folder_request,
    reveal_in_explorer, user_explanation,
)
from semantic_intent_router import suitable_for_semantic_routing
from text_only_main import TextJarvis


class NeverDeleteUserFilesTests(unittest.TestCase):
    def test_all_explicit_delete_phrasings_intercept_before_ai(self):
        phrases={
            "удали файл":"file",
            "Джарвис, удали фотографии":"file",
            "хочу удалить видео":"file",
            "можешь стереть файл":"file",
            "сотри программу":"file",
            "снеси папку":"folder",
            "удалить каталог":"folder",
            "очисти папку":"folder",
            "очисти корзину":"folder",
            "выкинь этот файл":"file",
            "отправь файл в корзину":"file",
            "delete folder":"file",
        }
        for phrase,kind in phrases.items():
            with self.subTest(phrase=phrase):
                self.assertTrue(is_delete_request(phrase))
                intent=route_chat_request(phrase)
                self.assertEqual(intent,ChatIntent("manual_delete",kind))
                self.assertFalse(suitable_for_semantic_routing(phrase))
                plan=parse_local(phrase)
                self.assertFalse(plan.steps)
                self.assertIn("не удаляет",plan.answer)
                with mock.patch("agent_core.request_json") as ai:
                    answer=ask_ai_for_plan(phrase,engine="openai")
                self.assertFalse(answer.steps)
                ai.assert_not_called()

    def test_negation_questions_and_examples_do_not_open_chooser(self):
        for phrase in (
            "не удаляй файл", "Джарвис, не удаляй папку",
            "как удалить файл", "почему удалён файл",
            "если я скажу удали папку", "объясни как удалить",
            "удаление файлов", "очисти поле ввода",
            "убери окно", "не нужно удалять проект",
            '«удали всё»', "представь что ты удаляешь",
        ):
            with self.subTest(phrase=phrase):
                self.assertFalse(is_delete_request(phrase))
                intent=route_chat_request(phrase)
                self.assertTrue(intent is None or intent.kind!="manual_delete")

    def test_voice_and_text_dispatch_only_open_manual_location(self):
        user=mock.Mock()
        user._closing=False
        Jarvis.handle_text(user,"удали мою папку")
        user.show_manual_delete_location.assert_called_once_with(folder=True)
        user.execute_plan.assert_not_called()
        user.open_code_assistant.assert_not_called()
        user.desktop.execute.assert_not_called()
        user.local_chat.ask.assert_not_called()

        app=mock.Mock()
        TextJarvis._dispatch_chat_first(
            app,ChatIntent("manual_delete","file"),"удали файл")
        app.show_manual_delete_location.assert_called_once_with(folder=False)
        app.execute_plan.assert_not_called()
        app.download_local_model.assert_not_called()
        app.open_code_assistant.assert_not_called()

    def test_controller_never_reports_deleted_content(self):
        app=mock.Mock()
        with mock.patch("main.choose_for_manual_deletion",
                        return_value=Path("C:/Users/User/example.txt")) as choose:
            Jarvis.show_manual_delete_location(app,folder=False)
        choose.assert_called_once_with(parent=app,folder=False)
        self.assertIn("не удаляет",app.reply.call_args_list[0].args[0])
        self.assertIn("Ничего не удалено",app.reply.call_args_list[1].args[0])

        app=mock.Mock()
        with mock.patch("main.choose_for_manual_deletion",return_value=None):
            Jarvis.show_manual_delete_location(app,folder=True)
        self.assertIn("Ничего не удалено",app.reply.call_args_list[-1].args[0])

    def test_reveal_file_and_folder_does_not_modify_contents(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            file=directory/"приватный файл.txt"
            file.write_bytes(b"DO NOT DELETE OR READ ME")
            calls=[]
            def launch(args,**kwargs):
                calls.append((args,kwargs))
            selected=reveal_in_explorer(
                file,launcher=launch,platform="nt")
            self.assertEqual(selected,file.absolute())
            self.assertEqual(len(calls),1)
            argv,options=calls[0]
            self.assertTrue(argv[0].lower().endswith("explorer.exe"))
            self.assertEqual(argv[1],"/select,")
            self.assertEqual(argv[2],str(file.absolute()))
            self.assertIs(options["shell"],False)
            self.assertEqual(file.read_bytes(),b"DO NOT DELETE OR READ ME")

            reveal_in_explorer(directory,launcher=launch,platform="nt")
            self.assertEqual(calls[-1][0][1:], [str(directory.absolute())])
            self.assertTrue(file.exists())

    def test_chooser_is_explicit_and_cancellation_is_inert(self):
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/"keep.txt"
            file.write_text("keep",encoding="utf-8")
            called=[]
            def launch(args,**kwargs):
                called.append(args)
            chosen=choose_for_manual_deletion(
                parent=None, folder=False,
                file_picker=lambda **kwargs:str(file),
                directory_picker=lambda **kwargs:self.fail("no folder dialog"),
                launcher=launch, platform="nt")
            self.assertEqual(chosen,file.absolute())
            self.assertEqual(file.read_text(),"keep")
            self.assertEqual(len(called),1)
            nothing=choose_for_manual_deletion(
                folder=True,
                file_picker=lambda **kwargs:self.fail("no file dialog"),
                directory_picker=lambda **kwargs:"",
                launcher=launch,platform="nt")
            self.assertIsNone(nothing)
            self.assertEqual(len(called),1)

    def test_nonexistent_items_and_unsupported_os_do_not_execute(self):
        launcher=mock.Mock()
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileNotFoundError):
                reveal_in_explorer(
                    Path(root)/"missing.txt",
                    launcher=launcher,platform="nt")
            launcher.assert_not_called()
            with self.assertRaises(OSError):
                reveal_in_explorer(root,launcher=launcher,platform="posix")
        self.assertIn("сам",user_explanation())

    def test_runtime_outputs_have_no_delete_or_rollback_erase_calls(self):
        root=Path(__file__).resolve().parents[1]
        protected=(
            "video_timeline.py", "popular_edits.py", "multitrack_composer.py",
            "online_media.py", "post_montage_review.py", "code_workspace.py",
            "code_edits.py", "updater_worker.py",
        )
        for filename in protected:
            with self.subTest(filename=filename):
                source=(root/filename).read_text(encoding="utf-8")
                for prohibited in (".unlink(", ".rmdir(", "os.remove(",
                                   "shutil.rmtree("):
                    self.assertNotIn(prohibited,source)


if __name__=="__main__":
    unittest.main()

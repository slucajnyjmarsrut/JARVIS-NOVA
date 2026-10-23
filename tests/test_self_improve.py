# -*- coding: utf-8 -*-
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from self_improve import LearningStore, safe_name, propose_installed_name
from desktop import Desktop, AppSuggestion


class SelfImprovementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'JarvisNova' / 'learning.json'
        self.learning = LearningStore(self.path)

    def test_requires_verified_real_program(self):
        with self.assertRaises(PermissionError):
            self.learning.learn('хрмо', 'Google Chrome')
        self.assertFalse(self.path.exists())

    def test_learns_and_restores_after_restart(self):
        self.learning.learn('хрмо', 'Google Chrome', verified=True)
        reread = LearningStore(self.path)
        self.assertEqual(reread.resolve('ХРМО'), 'Google Chrome')

    def test_learns_only_safe_names(self):
        for spoken, target in [('../oops', 'Steam'), ('открыть', 'cmd'),
                               ('steam; shutdown', 'Steam'), ('https://evil.test', 'Steam'),
                               ('электричество', 'powershell')]:
            with self.subTest(spoken=spoken):
                with self.assertRaises(ValueError):
                    self.learning.learn(spoken, target, verified=True)

    def test_no_raw_utterances_in_statistics(self):
        self.learning.feedback('open_app', False)
        self.learning.feedback('open_app', True)
        self.learning.feedback('открой мой пароль', False)
        doc = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(doc['stats']['open_app'], {'ok': 1, 'fail': 1})
        self.assertNotIn('пароль', self.path.read_text(encoding='utf-8'))

    def test_store_rejects_malicious_json_data(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({'version': 1,
          'aliases': {'среда': 'powershell', 'стимм': 'Steam', '../bad': 'Steam'},
          'stats': {'type': {'ok': 10000000000, 'fail': -8}}}), encoding='utf-8')
        restored = LearningStore(self.path)
        self.assertEqual(restored.resolve('стимм'), 'Steam')
        self.assertIsNone(restored.resolve('среда'))
        self.assertEqual(restored.stats['type']['ok'], 1000000)
        self.assertEqual(restored.stats['type']['fail'], 0)

    def test_corrupted_json_does_not_crash(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{not json', encoding='utf-8')
        restored = LearningStore(self.path)
        self.assertEqual(restored.aliases, {})

    def test_corrupted_learning_file_is_never_implicitly_overwritten(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        original=b"{corrupted data"
        self.path.write_bytes(original)
        other=LearningStore(self.path)
        self.assertEqual(other.aliases,{})
        other.feedback("open_app",True)  # optional feedback must not crash
        with self.assertRaisesRegex(RuntimeError,"ручная проверка"):
            other.learn("программа","Notepad",verified=True)
        with self.assertRaisesRegex(RuntimeError,"ручная проверка"):
            other.reset()
        self.assertEqual(self.path.read_bytes(),original)
        self.assertEqual(other.aliases,{})
        self.assertIn("запись отключена",other.summary())
        self.assertEqual(list(self.path.parent.glob("*.tmp")),[])

    def test_future_version_and_oversize_learning_are_read_only(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        originals=[
            json.dumps({"version":99,"aliases":{"x":"Notepad"}}).encode(),
            b"x"*41_000,
        ]
        for payload in originals:
            with self.subTest(length=len(payload)):
                self.path.write_bytes(payload)
                store=LearningStore(self.path)
                store.feedback("open_app",True)
                with self.assertRaises(RuntimeError):
                    store.learn("приложение","Notepad",verified=True)
                self.assertEqual(self.path.read_bytes(),payload)

    def test_competing_jarvis_cannot_erase_another_instances_learned_alias(self):
        self.learning.learn("магазин","Steam",verified=True)
        second=LearningStore(self.path)
        self.learning.learn("редактор","Notepad",verified=True)
        expected=self.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError,"другим процессом"):
            second.learn("браузер","Google Chrome",verified=True)
        self.assertEqual(self.path.read_bytes(),expected)
        self.assertIsNone(second.resolve("браузер"))
        self.assertEqual(LearningStore(self.path).resolve("редактор"),"Notepad")
        second.feedback("open_app",True)  # shouldn't throw, shouldn't overwrite
        self.assertEqual(self.path.read_bytes(),expected)

    def test_learning_reset_cannot_erase_file_modified_externally(self):
        self.learning.learn("стимм","Steam",verified=True)
        external='{"version":1,"aliases":{"вручную":"Notepad"},"stats":{}}'.encode("utf-8")
        self.path.write_bytes(external)
        with self.assertRaisesRegex(RuntimeError,"другим процессом"):
            self.learning.reset()
        self.assertEqual(self.path.read_bytes(),external)
        self.assertEqual(self.learning.resolve("стимм"),"Steam")

    def test_user_can_rollback_learning(self):
        self.learning.learn('стимм', 'Steam', verified=True)
        self.assertTrue(self.learning.unlearn('стимм'))
        self.assertIsNone(LearningStore(self.path).resolve('стимм'))
        self.learning.learn('стимм', 'Steam', verified=True)
        self.learning.feedback('open_app', False)
        self.learning.reset()
        restored = LearningStore(self.path)
        self.assertEqual(restored.aliases, {})
        self.assertEqual(restored.stats, {})

    def test_limits_automatic_learning_count(self):
        for i in range(120):
            self.learning.learn(f'программа {i}', 'Steam', verified=True)
        with self.assertRaises(ValueError):
            self.learning.learn('программа последняя', 'Steam', verified=True)

    def test_fuzzy_suggestion_no_execution(self):
        suggestion = propose_installed_name('Steem', ['Steam', 'Google Chrome', 'Notepad'])
        self.assertEqual(suggestion, 'Steam')
        self.assertIsNone(propose_installed_name('open internet', ['Steam']))
        self.assertIsNone(propose_installed_name('steam', ['Steam']))

    def test_shortcut_proposed_but_not_run_without_confirmation(self):
        d = Desktop(learning=self.learning)
        with mock.patch.object(d, 'shortcuts', return_value=[Path('C:/Fake/Steam.lnk')]), \
             mock.patch('desktop.os.startfile', create=True) as launcher:
            with self.assertRaises(AppSuggestion) as cm:
                d.open_app('Steem')
            self.assertEqual(cm.exception.installed, 'Steam')
            launcher.assert_not_called()

    def test_learned_alias_rechecks_installed_target(self):
        self.learning.learn('стимм', 'Steam', verified=True)
        d=Desktop(learning=self.learning)
        with mock.patch.object(d, 'shortcuts', return_value=[]), \
             mock.patch('desktop.os.startfile', create=True) as launcher:
            with self.assertRaises(FileNotFoundError):
                d.open_app('стимм')
            launcher.assert_not_called()

    def test_confirmed_alias_launches_only_verified_shortcut(self):
        self.learning.learn('стимм', 'Steam', verified=True)
        d=Desktop(learning=self.learning)
        with mock.patch.object(d, 'shortcuts', return_value=[Path('C:/Start/Steam.lnk')]), \
             mock.patch('desktop.os.startfile', create=True) as launcher:
            self.assertIn('Steam', d.open_app('стимм'))
            launcher.assert_called_once_with(str(Path('C:/Start/Steam.lnk')))


if __name__=='__main__':
    unittest.main()

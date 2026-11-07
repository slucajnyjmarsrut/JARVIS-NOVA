import json
import tempfile
import unittest
from pathlib import Path

from code_edits import snapshot_project, write_reviewed_update
from code_autopilot import generate_and_check, install_reviewed
from code_workspace import WorkspaceError, ProposedFile, ChangePlan


def java_proposal(contents):
    return json.dumps({'language':'java','files':[{'path':'Main.java','content':contents}]})


class EditingTests(unittest.TestCase):
    def test_update_existing_compiles_backups(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'Main.java').write_text('public class Main { public static void main(String[] a) {} }',encoding='utf-8')
            original=(root/'Main.java').read_bytes()
            new='public class Main { public static void main(String[] a) { System.out.println("ok"); } }'
            result=generate_and_check('Add output','java',workspace=root,
                                      generator=lambda *_:java_proposal(new))
            self.assertTrue(result.verified)
            self.assertEqual((root/'Main.java').read_bytes(),original)
            with self.assertRaises(PermissionError):install_reviewed(result,root)
            paths=install_reviewed(result,root,confirmed=True)
            self.assertEqual(len(paths),1)
            self.assertEqual((root/'Main.java').read_text(encoding='utf-8'),new)
            backups=list((root/'.jarvis_code_backups').glob('revision-*/Main.java'))
            self.assertEqual(len(backups),1)
            self.assertEqual(backups[0].read_bytes(),original)
            with self.assertRaises(WorkspaceError):install_reviewed(result,root,confirmed=True)
    def test_reject_file_changed_since_preview(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            original='class Main {}'
            file=root/'Main.java'
            file.write_text(original)
            result=generate_and_check('Add notes','java',workspace=root,
                                      generator=lambda *_:java_proposal('class Main { }'))
            file.write_text('class Main { int race; }')
            with self.assertRaises(WorkspaceError):install_reviewed(result,root,confirmed=True)
            self.assertIn('race',file.read_text())
    def test_reject_unknown_old_file(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'Main.java').write_text('class Main {}')
            snapshot,sums=snapshot_project(root,'java')
            self.assertIn('Main.java',snapshot)
            (root/'Other.java').write_text('class Other {}')
            with self.assertRaises(WorkspaceError):
                write_reviewed_update(ChangePlan('java',(ProposedFile('Other.java','class Other {}'),)),
                                      root,sums,confirmed=True)
    def test_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            root=Path(d)
            (root/'source').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(WorkspaceError):snapshot_project(root,'java')
    def test_reject_invalid_generated_java(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            src=root/'Main.java'
            src.write_text('class Main {}')
            result=generate_and_check('Break it','java',workspace=root,
                                      generator=lambda *_:java_proposal('class Main { syntax error }'),
                                      max_attempts=1)
            self.assertFalse(result.verified)
            with self.assertRaises(WorkspaceError):install_reviewed(result,root,confirmed=True)
            self.assertEqual(src.read_text(),'class Main {}')


if __name__=='__main__':unittest.main()

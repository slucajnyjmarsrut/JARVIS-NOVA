"""Security regression: published Windows release hashes must fail closed."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from scripts.check_release_hashes import verify_release_hashes


class ReleaseSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.name="JARVIS-NOVA-0.5.7-OFFLINE-SETUP-DEV.exe"
        self.exe=self.folder/self.name
        self.exe.write_bytes(b"synthetic test setup")
        self.digest=hashlib.sha256(self.exe.read_bytes()).hexdigest()
        self.sums=self.folder/"SHA256SUMS.txt"
        self.sums.write_text(f"{self.digest}  {self.name}\n",encoding="utf-8")

    def test_valid_full_hash_is_accepted(self):
        name,digest=verify_release_hashes(self.folder)
        self.assertEqual((name,digest),(self.name,self.digest))

    def test_changed_executable_is_rejected(self):
        self.exe.write_bytes(self.exe.read_bytes()+b"unauthorized change")
        with self.assertRaisesRegex(ValueError,"mismatch"):
            verify_release_hashes(self.folder)

    def test_path_traversal_is_rejected(self):
        self.sums.write_text(f"{self.digest}  ../{self.name}\n",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"Unsafe"):
            verify_release_hashes(self.folder)

    def test_no_or_duplicate_hashes_is_rejected(self):
        self.sums.write_text("",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"ONE"):
            verify_release_hashes(self.folder)
        self.sums.write_text(f"{self.digest}  {self.name}\n{self.digest}  {self.name}\n",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"ONE"):
            verify_release_hashes(self.folder)

    def test_unknown_extra_executable_is_rejected(self):
        (self.folder/"suspicious.exe").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError,"mismatch"):
            verify_release_hashes(self.folder)

    def test_bad_digest_and_wrong_file_type_are_rejected(self):
        self.sums.write_text(f"xxxx  {self.name}\n",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"digest"):
            verify_release_hashes(self.folder)
        self.sums.write_text(f"{self.digest}  suspicious.zip\n",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"EXE"):
            verify_release_hashes(self.folder)


if __name__=="__main__":
    unittest.main()

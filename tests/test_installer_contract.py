"""Contract checks only — NOT a substitute for real Windows model inference."""
from pathlib import Path
import struct
import tempfile
import unittest
from scripts.verify_installer_payload import is_windows_64_executable, verify

ROOT=Path(__file__).resolve().parent.parent

class InstallerContractTests(unittest.TestCase):
    def test_pe64_architecture_check(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'test.exe'
            path.write_bytes(b'fake')
            self.assertFalse(is_windows_64_executable(path))
            data=bytearray(512);data[:2]=b'MZ'
            struct.pack_into('<I',data,0x3c,0x80)
            data[0x80:0x84]=b'PE\0\0'
            struct.pack_into('<H',data,0x84,0x14c)
            struct.pack_into('<H',data,0x98,0x10b)
            path.write_bytes(data)
            self.assertFalse(is_windows_64_executable(path))
            struct.pack_into('<H',data,0x84,0x8664)
            struct.pack_into('<H',data,0x98,0x20b)
            path.write_bytes(data)
            self.assertTrue(is_windows_64_executable(path))

    def test_fail_closed_without_package(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(RuntimeError,'x64 app'):
                verify(Path(td))

    def test_single_exe_wizard_and_data_preservation(self):
        text=(ROOT/'installer/JarvisNova.iss').read_text(encoding='utf-8')
        for item in ('DiskSpanning=no','PrivilegesRequired=lowest','AppMutex=JarvisNovaRuntime',
                     'DefaultDirName={localappdata}', 'CloseApplications=yes',
                     'RestartApplications=no','MinVersion=10.0','recursesubdirs'):
            self.assertIn(item,text)
        files=text.split('[Files]')[1].split('[Tasks]')[0]
        self.assertNotIn('download',files.lower())
        self.assertNotIn('\n[UninstallDelete]\n',text)

    def test_update_version_agrees_with_installer_and_windows_metadata(self):
        from auto_update import APP_VERSION
        iss=(ROOT/'installer/JarvisNova.iss').read_text(encoding='utf-8')
        packaged=(ROOT/'assets/APP_RELEASE_VERSION.txt').read_text('ascii').strip()
        self.assertEqual(APP_VERSION,packaged)
        self.assertIn(f'#define AppVersion "{APP_VERSION}-dev"',iss)
        self.assertIn(f'OutputBaseFilename=JARVIS-NOVA-{APP_VERSION}-OFFLINE-SETUP-DEV',iss)
        self.assertIn(f'VersionInfoVersion={APP_VERSION}.0',iss)
        self.assertIn('JarvisNovaUpdater.exe',iss)

    def test_real_exe_and_installer_gates_are_not_mocked(self):
        workflow=(ROOT/'.github/workflows/windows-offline.yml').read_text(encoding='utf-8')
        self.assertIn('verify_installer_payload.py',workflow)
        self.assertIn('test_installer.ps1',workflow)
        self.assertIn('offline_e2e_test.py',workflow)
        self.assertIn('verify_offline_distribution.ps1',workflow)

if __name__ == '__main__':
    unittest.main()

"""Windows launcher encoding regression guard.

CMD scripts must be written with CRLF line endings. This tests checked-out
files, not a simulated cmd.exe runtime.
"""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class WindowsLauncherTests(unittest.TestCase):
    def test_batch_scripts_have_crlf_only(self):
        scripts = sorted(ROOT.glob("*.bat"))
        self.assertGreaterEqual(len(scripts), 3)
        for file in scripts:
            with self.subTest(script=file.name):
                data = file.read_bytes()
                self.assertIn(b'\r\n', data)
                self.assertNotIn(b'\n', data.replace(b'\r\n', b''))
                self.assertNotIn(b'\r', data.replace(b'\r\n', b''))
                self.assertFalse(data.startswith(b'\xef\xbb\xbf'))

    def test_ai_launcher_calls_powershell_by_absolute_path(self):
        data = (ROOT / 'start_ai_windows.bat').read_bytes()
        self.assertIn(b'%SystemRoot%', data)
        self.assertIn(b'powershell.exe', data)
        self.assertIn(b'start_ai_windows.ps1', data)
        self.assertTrue((ROOT / 'start_ai_windows.ps1').is_file())

if __name__ == '__main__':
    unittest.main()

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from backend.settings import Settings


class SettingsTests(unittest.TestCase):
    def test_local_token_is_private_and_stable(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'LEADDESK_DATA_DIR':str(Path(temp)/'data')}):
            first = Settings.load()
            self.assertGreaterEqual(len(first.token),32)
            self.assertEqual(Settings.load().token,first.token)
            self.assertEqual(stat.S_IMODE((first.data_dir/'access-token').stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE(first.data_dir.stat().st_mode),0o700)

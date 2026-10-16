"""Cache scan failures must preserve the previous cache."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/cache.sh'
BASH = os.environ.get('MISTER_TEST_BASH', '/bin/bash')


class CacheSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mister-cache-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.card = self.base / 'card'
        self.card.mkdir()
        self.cache = self.base / 'cache'
        self.cache.write_text('NES/previous.nes\tNES\n')
        self.env = dict(os.environ, CACHE_FILE=str(self.cache),
                        MISTER_SIMP_LOG_FILE=str(self.base / 'log'))

    def run_cache(self):
        return subprocess.run([BASH, str(SCRIPT), str(self.card)],
                              env=self.env, capture_output=True, text=True)

    def assert_preserved(self):
        self.assertEqual(self.cache.read_text(), 'NES/previous.nes\tNES\n')
        self.assertEqual(list(self.base.glob('cache.*')), [])

    def test_missing_games_root_preserves_cache(self):
        self.assertNotEqual(self.run_cache().returncode, 0)
        self.assert_preserved()

    def test_failed_scan_preserves_cache_and_removes_partial_files(self):
        (self.card / 'games/NES').mkdir(parents=True)
        bindir = self.base / 'bin'
        bindir.mkdir()
        find = bindir / 'find'
        find.write_text('#!/bin/bash\nprintf "partial"\nexit 1\n')
        find.chmod(0o755)
        self.env['PATH'] = str(bindir) + ':' + os.environ['PATH']
        self.assertNotEqual(self.run_cache().returncode, 0)
        self.assert_preserved()

    def test_old_temp_symlink_is_not_followed(self):
        nes = self.card / 'games/NES'
        nes.mkdir(parents=True)
        (nes / 'keep.nes').write_bytes(b'rom')
        outside = self.base / 'outside'
        outside.write_bytes(b'outside original')
        old_temp = self.base / 'cache.tmp'
        old_temp.symlink_to(outside)
        self.assertEqual(self.run_cache().returncode, 0)
        self.assertEqual(outside.read_bytes(), b'outside original')
        self.assertTrue(old_temp.is_symlink())
        self.assertEqual(self.cache.read_text(), 'NES/keep.nes\tNES\n')
        self.assertEqual(list(self.base.glob('cache.tmp.*')), [])
        self.assertEqual(list(self.base.glob('cache.scan.*')), [])

    def test_directory_destination_is_refused(self):
        (self.card / 'games/NES').mkdir(parents=True)
        self.cache.unlink()
        self.cache.mkdir()
        self.assertNotEqual(self.run_cache().returncode, 0)
        self.assertEqual(list(self.cache.iterdir()), [])
        self.assertEqual(list(self.base.glob('cache.*')), [])

    def test_family_symlinks_refuse_without_replacing_cache(self):
        games = self.card / 'games'
        games.mkdir()
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'keep.nes').write_bytes(b'outside')
        family = games / 'NES'
        for target in (outside, self.base / 'missing'):
            with self.subTest(target=target):
                family.symlink_to(target, target_is_directory=True)
                self.assertNotEqual(self.run_cache().returncode, 0)
                self.assert_preserved()
                self.assertEqual((outside / 'keep.nes').read_bytes(), b'outside')
                family.unlink()

    def test_success_with_optional_missing_families(self):
        nes = self.card / 'games/NES'
        nes.mkdir(parents=True)
        (nes / 'keep.nes').write_bytes(b'rom')
        self.assertEqual(self.run_cache().returncode, 0)
        self.assertEqual(self.cache.read_text(), 'NES/keep.nes\tNES\n')
        self.assertEqual(list(self.base.glob('cache.*')), [])


if __name__ == '__main__':
    unittest.main()

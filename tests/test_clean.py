"""Focused cleanup safety fixtures; never operate on a real card."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

BASH = os.environ.get('MISTER_TEST_BASH', '/bin/bash')
SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/clean.sh'


class CleanSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mister-clean-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.card = self.base / 'card'
        self.card.mkdir()
        for name in ('MiSTer', 'menu.rbf'):
            (self.card / name).write_bytes(b'card marker')
        self.home = self.base / 'home'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home),
                        MISTER_TIDY_LOG_FILE=str(self.base / 'audit.log'))

    def run_clean(self, target):
        return subprocess.run([BASH, str(SCRIPT), str(target)],
                              env=self.env, capture_output=True, text=True)

    def snapshot(self, root):
        return {str(p.relative_to(root)): p.read_bytes()
                for p in root.rglob('*') if p.is_file()}

    def test_invalid_targets_refuse_without_mutation(self):
        wrong = self.base / 'wrong'
        wrong.mkdir()
        (wrong / 'keep').write_bytes(b'untouched')
        empty = self.base / 'empty'
        empty.mkdir()
        # Include a home directory that otherwise looks like a card.
        for name in ('MiSTer', 'menu.rbf', 'keep'):
            (self.home / name).write_bytes(b'untouched')
        before = self.snapshot(self.base)
        for target in ('', '/', '///', self.home, wrong, empty, self.base / 'missing'):
            with self.subTest(target=target):
                result = self.run_clean(target)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.snapshot(self.base), before)

    def test_cleanup_preserves_state_and_removes_nested_blacklist(self):
        scripts = self.card / 'scripts'
        scripts.mkdir()
        for name in ('.cache', '.mgl', '.manifest', '.log'):
            (scripts / name).write_bytes(name.encode())
        palettes = self.card / 'games/NES/Palettes'
        palettes.mkdir(parents=True)
        (palettes / 'test.pal').write_bytes(b'blacklisted')
        rom = palettes.parent / 'keep.nes'
        rom.write_bytes(b'rom')
        (scripts / 'obsolete').write_bytes(b'delete')
        result = self.run_clean(self.card)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ('.cache', '.mgl', '.manifest', '.log'):
            self.assertEqual((scripts / name).read_bytes(), name.encode())
        self.assertFalse(palettes.exists())
        self.assertEqual(rom.read_bytes(), b'rom')
        self.assertFalse((scripts / 'obsolete').exists())

    def test_removed_platforms_are_pruned_but_sms_survives(self):
        for name in ('games/S32X/game.32x', 'games/NeoGeoPocket/game.ngp', 'S32X_20261016.rbf',
                     'games/SMS/nested/game.gg', 'games/SMS/other.Gg',
                     'games/SMS/keep.sms'):
            dest = self.card / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b'fixture')
        result = self.run_clean(self.card)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.card / 'games/S32X').exists())
        self.assertFalse((self.card / 'games/NeoGeoPocket').exists())
        self.assertFalse((self.card / 'S32X_20261016.rbf').exists())
        self.assertFalse((self.card / 'games/SMS/nested/game.gg').exists())
        self.assertFalse((self.card / 'games/SMS/other.Gg').exists())
        self.assertEqual((self.card / 'games/SMS/keep.sms').read_bytes(), b'fixture')

    def test_games_pruning_covers_loose_hidden_and_dangling_entries(self):
        games = self.card / 'games'
        (games / 'NES').mkdir(parents=True)
        (games / 'NES/keep.nes').write_bytes(b'rom')
        (games / 'loose.bin').write_bytes(b'unsupported')
        (games / '.hidden').mkdir()
        (games / '.hidden/keep').write_bytes(b'unsupported')
        (games / 'dangling').symlink_to(self.base / 'missing')
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'keep').write_bytes(b'outside')
        (games / 'unsupported-link').symlink_to(outside, target_is_directory=True)
        result = self.run_clean(self.card)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([p.name for p in games.iterdir()], ['NES'])
        self.assertEqual((games / 'NES/keep.nes').read_bytes(), b'rom')
        self.assertEqual((outside / 'keep').read_bytes(), b'outside')

    def test_case_collision_preserves_every_file(self):
        upper = self.card / 'Games'
        lower = self.card / 'games'
        upper.mkdir()
        if lower.exists():
            self.skipTest('Games/games coexistence requires a case-sensitive filesystem')
        lower.mkdir()
        (upper / 'a').write_bytes(b'upper contents')
        (lower / 'b').write_bytes(b'lower contents')
        before = self.snapshot(self.card)
        self.assertNotEqual(self.run_clean(self.card).returncode, 0)
        self.assertEqual(self.snapshot(self.card), before)

    def test_case_only_rename_preserves_rom(self):
        rom = self.card / 'Games/nes/keep.nes'
        rom.parent.mkdir(parents=True)
        rom.write_bytes(b'rom')
        result = self.run_clean(self.card)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.card / 'games/NES/keep.nes').read_bytes(), b'rom')

    def test_symlink_card_folder_refuses(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'keep').write_bytes(b'outside')
        (self.card / 'games').symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(self.run_clean(self.card).returncode, 0)
        self.assertEqual((outside / 'keep').read_bytes(), b'outside')

    def test_collision_guard_preserves_distinct_destinations(self):
        # Exercise the guard even on case-insensitive host filesystems.
        a, b = self.base / 'source', self.base / 'destination'
        a.mkdir()
        b.mkdir()
        (a / 'a').write_bytes(b'source')
        (b / 'b').write_bytes(b'destination')
        before = self.snapshot(self.base)
        source = SCRIPT.read_text()
        helpers = source[source.index('check_destination()'):source.index('canonical_from_whitelist()')]
        result = subprocess.run([BASH, '-c',
                                 'set -euo pipefail\n' + helpers + '\nmove_or_rename "$1" "$2"',
                                 'fixture', str(a), str(b)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(self.base), before)


if __name__ == '__main__':
    unittest.main()

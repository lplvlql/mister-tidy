"""Launcher/deletion fixtures use a regular command file, never MiSTer hardware."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

BASH = os.environ.get('MISTER_TEST_BASH', '/bin/bash')
SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
from test_update import run_stage


class LaunchDelete(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mister-launch-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.card = self.base / 'card'
        self.games = self.card / 'games'
        self.games.mkdir(parents=True)
        for marker in ('MiSTer', 'menu.rbf'):
            (self.card / marker).write_bytes(b'card marker')
        self.cache = self.base / 'cache'
        self.mgl = self.base / 'last.mgl'
        self.command = self.base / 'command'
        self.env = dict(os.environ, CACHE_FILE=str(self.cache), MGL_FILE=str(self.mgl),
                        SHUFFLE_FILE=str(self.base / 'shuffle'), MISTER_CMD=str(self.command), MISTER_TIDY_LOG_FILE=str(self.base / 'log'))

    def run_script(self, name):
        return subprocess.run([BASH, str(SCRIPTS / name), str(self.card)],
                              env=self.env, capture_output=True, text=True)

    def game(self, name):
        path = self.games / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'rom')
        return path

    def test_shuffle_plays_every_game_before_reset(self):
        games = {str(self.game(f'NES/{name}.nes')) for name in ('a', 'b', 'c')}
        self.assertEqual(run_stage('build_cache', self.card, self.env).returncode, 0)
        picks = []
        for _ in range(6):
            result = self.run_script('shuffle.sh')
            self.assertEqual(result.returncode, 0, result.stderr)
            picks.append(ET.parse(self.mgl).find('file').attrib['path'])
        self.assertEqual(set(picks[:3]), games)
        self.assertEqual(set(picks[3:]), games)

    def test_cache_excludes_removed_platforms_and_keeps_sms(self):
        for name in ('SMS/test.gg', 'SMS/test.GG', 'S32X/test.32x', 'SMS/keep.sms'):
            self.game(name)
        self.assertEqual(run_stage('build_cache', self.card, self.env).returncode, 0)
        self.assertEqual(self.cache.read_text(), 'SMS/keep.sms\tSMS f 1 1\n')
        self.assertEqual(self.run_script('shuffle.sh').returncode, 0)
        entry = ET.parse(self.mgl).find('file')
        self.assertEqual(entry.attrib['type'], 'f')
        self.assertEqual(entry.attrib['index'], '1')
        self.assertEqual(entry.attrib['delay'], '1')

    def test_unknown_types_never_write_mgl_or_launch(self):
        for rel, core in [('SMS/test.gg', 'SMS'), ('S32X/test.32x', 'S32X'),
                          ('NES/test.unknown', 'NES')]:
            with self.subTest(rel=rel):
                self.game(rel)
                self.cache.write_text(f'{rel}\t{core}\n')
                self.mgl.unlink(missing_ok=True)
                self.command.write_text('unchanged command')
                self.assertNotEqual(self.run_script('shuffle.sh').returncode, 0)
                self.assertFalse(self.mgl.exists())
                self.mgl.write_text('previous last game')
                self.assertNotEqual(self.run_script('shuffle.sh').returncode, 0)
                self.assertEqual(self.mgl.read_text(), 'previous last game')
                self.assertEqual(self.command.read_text(), 'unchanged command')

    def test_mgl_open_failure_never_sends_launch_command(self):
        self.game('NES/test.nes')
        self.cache.write_text('NES/test.nes\tNES f 1 2\n')
        self.env['MGL_FILE'] = str(self.base / 'missing-parent/last.mgl')
        self.command.write_text('previous command')
        result = self.run_script('shuffle.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.command.read_text(), 'previous command')
        self.assertFalse(Path(self.env['MGL_FILE']).exists())
        self.assertIn('Failed to write MGL:', (self.base / 'log').read_text())

    def test_mgl_stream_write_failure_never_sends_launch_command(self):
        self.game('NES/test.nes')
        self.cache.write_text('NES/test.nes\tNES f 1 2\n')
        bindir = self.base / 'bin'
        bindir.mkdir()
        cat = bindir / 'cat'
        cat.write_text('#!/bin/bash\nprintf "partial write"\nexit 1\n')
        cat.chmod(0o755)
        self.env['PATH'] = str(bindir) + ':' + os.environ['PATH']
        self.mgl.write_text('previous valid MGL')
        self.command.write_text('previous command')
        result = self.run_script('shuffle.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.command.read_text(), 'previous command')
        self.assertEqual(self.mgl.read_text(), 'previous valid MGL')
        self.assertEqual(list(self.base.glob('last.mgl.*')), [])
        self.assertIn('Failed to write MGL:', (self.base / 'log').read_text())

    def test_delete_prunes_cache_and_stale_entries_cannot_launch(self):
        target = self.game('NES/A [x] & B.nes')
        self.game('NES/keep.nes')
        self.cache.write_text('NES/A [x] & B.nes\tNES f 1 2\n')
        self.assertEqual(self.run_script('shuffle.sh').returncode, 0)
        self.cache.write_text('NES/A [x] & B.nes\tNES f 1 2\nNES/keep.nes\tNES f 1 2\n')
        self.assertEqual(self.run_script('delete.sh').returncode, 0)
        self.assertFalse(target.exists())
        self.assertEqual(self.cache.read_text(), 'NES/keep.nes\tNES f 1 2\n')
        self.cache.write_text('NES/A [x] & B.nes\tNES f 1 2\n')
        self.command.write_text('no launch')
        self.mgl.write_text('previous last game')
        self.assertNotEqual(self.run_script('shuffle.sh').returncode, 0)
        self.assertEqual(self.command.read_text(), 'no launch')
        self.assertEqual(self.mgl.read_text(), 'previous last game')
        self.cache.write_text('NES/missing.nes\tNES f 1 2\nNES/keep.nes\tNES f 1 2\n')
        self.assertEqual(self.run_script('shuffle.sh').returncode, 0)
        self.assertTrue(ET.parse(self.mgl).find('file').attrib['path'].endswith('/NES/keep.nes'))

    def test_mgl_directory_destination_is_not_treated_as_success(self):
        self.game('NES/test.nes')
        self.cache.write_text('NES/test.nes\tNES f 1 2\n')
        self.mgl.mkdir()
        self.command.write_text('no launch')
        self.assertNotEqual(self.run_script('shuffle.sh').returncode, 0)
        self.assertEqual(self.command.read_text(), 'no launch')
        self.assertEqual(list(self.mgl.iterdir()), [])
        self.assertEqual(list(self.base.glob('last.mgl.*')), [])

    def test_mgl_rename_failure_preserves_previous_selection(self):
        self.game('NES/test.nes')
        self.cache.write_text('NES/test.nes\tNES f 1 2\n')
        self.mgl.write_text('previous valid MGL')
        bindir = self.base / 'bin'
        bindir.mkdir()
        mv = bindir / 'mv'
        mv.write_text('#!/bin/bash\nexit 1\n')
        mv.chmod(0o755)
        self.env['PATH'] = str(bindir) + ':' + os.environ['PATH']
        self.command.write_text('no launch')
        self.assertNotEqual(self.run_script('shuffle.sh').returncode, 0)
        self.assertEqual(self.mgl.read_text(), 'previous valid MGL')
        self.assertEqual(self.command.read_text(), 'no launch')
        self.assertEqual(list(self.base.glob('last.mgl.*')), [])

    def test_escape_failure_preserves_mgl_and_sends_no_command(self):
        self.game('NES/test.nes')
        self.cache.write_text('NES/test.nes\tNES f 1 2\n')
        self.mgl.write_text('previous MGL')
        self.command.write_text('previous command')
        bindir = self.base / 'bin'
        bindir.mkdir()
        sed = bindir / 'sed'
        sed.write_text('#!/bin/bash\nexit 1\n')
        sed.chmod(0o755)
        self.env['PATH'] = str(bindir) + ':' + os.environ['PATH']
        self.assertNotEqual(self.run_script('shuffle.sh').returncode, 0)
        self.assertEqual(self.mgl.read_text(), 'previous MGL')
        self.assertEqual(self.command.read_text(), 'previous command')
        self.assertEqual(list(self.base.glob('last.mgl.*')), [])

    def test_delete_refuses_cache_directory_before_deleting_rom(self):
        target = self.game('NES/test.nes')
        ET.ElementTree(ET.Element('file', path=str(target))).write(self.mgl)
        self.cache.mkdir()
        original_mgl = self.mgl.read_bytes()
        self.assertNotEqual(self.run_script('delete.sh').returncode, 0)
        self.assertEqual(target.read_bytes(), b'rom')
        self.assertEqual(self.mgl.read_bytes(), original_mgl)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_random_index_reaches_beyond_32768_and_stays_in_bounds(self):
        source = (SCRIPTS / 'shuffle.sh').read_text()
        helper = source[source.index('random_index()'):source.index('if [[ ! -s "$CACHE_FILE" ]]')]
        code = 'set -euo pipefail\n' + helper + '\nRANDOM=123\nfor ((i=0; i<200; i++)); do random_index 40000; done\n'
        result = subprocess.run([BASH, '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = [int(x) for x in result.stdout.splitlines()]
        self.assertEqual(len(values), 200)
        self.assertTrue(all(0 <= x < 40000 for x in values))
        self.assertTrue(any(x >= 32768 for x in values))

    def test_last_rejects_missing_malformed_and_outside_targets(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'keep.nes').write_bytes(b'outside')
        (self.games / 'link').symlink_to(outside, target_is_directory=True)
        (self.games / 'file-link.nes').symlink_to(outside / 'keep.nes')
        targets = [self.games / 'NES/missing.nes',
                   self.games / '../outside/keep.nes',
                   self.games / '../../outside/keep.nes',
                   self.games / 'link/keep.nes', self.games / 'file-link.nes']
        for target in targets:
            with self.subTest(target=target):
                ET.ElementTree(ET.Element('file', path=str(target))).write(self.mgl)
                before = self.mgl.read_bytes()
                self.command.write_text('previous command')
                self.assertNotEqual(self.run_script('repeat.sh').returncode, 0)
                self.assertEqual(self.command.read_text(), 'previous command')
                self.assertEqual(self.mgl.read_bytes(), before)
        for content in ('', 'broken XML', '<mistergamedescription/>'):
            self.mgl.write_text(content)
            self.command.write_text('previous command')
            self.assertNotEqual(self.run_script('repeat.sh').returncode, 0)
            self.assertEqual(self.command.read_text(), 'previous command')
        self.assertEqual((outside / 'keep.nes').read_bytes(), b'outside')

    def test_last_reloads_valid_escaped_rom_and_refuses_after_removal(self):
        name = 'NES/nested/A "quoted" <B> & literal &lt;.nes'
        target = self.game(name)
        self.cache.write_text(f'{name}\tNES f 1 2\n')
        self.assertEqual(self.run_script('shuffle.sh').returncode, 0)
        self.command.write_text('previous command')
        self.assertEqual(self.run_script('repeat.sh').returncode, 0)
        self.assertEqual(self.command.read_text(), f'load_core {self.mgl}\n')
        target.unlink()
        self.command.write_text('previous command')
        self.assertNotEqual(self.run_script('repeat.sh').returncode, 0)
        self.assertEqual(self.command.read_text(), 'previous command')

    def test_delete_refuses_traversal_and_external_symlinks(self):
        outside = self.base / 'outside'
        outside.mkdir()
        target = outside / 'keep.nes'
        target.write_bytes(b'outside')
        (self.games / 'link').symlink_to(outside, target_is_directory=True)
        (self.games / 'file-link.nes').symlink_to(target)
        paths = [str(self.games / '../../outside/keep.nes'),
                 str(self.games / 'link/keep.nes'),
                 str(self.games / 'file-link.nes')]
        for path in paths:
            with self.subTest(path=path):
                ET.ElementTree(ET.Element('file', path=path)).write(self.mgl)
                before = self.mgl.read_bytes()
                result = self.run_script('delete.sh')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), b'outside')
                self.assertEqual(self.mgl.read_bytes(), before)
                self.assertTrue((self.games / 'file-link.nes').is_symlink())

    def test_delete_allows_resolved_nested_in_tree_target(self):
        target = self.game('NES/nested/keep.nes')
        ET.ElementTree(ET.Element('file', path=str(target))).write(self.mgl)
        result = self.run_script('delete.sh')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(target.exists())
        self.assertFalse(self.mgl.exists())

    def test_xml_filename_round_trip_delete(self):
        for name in ['A & B.nes', 'A "quoted" <B>.nes', 'literal &lt; &gt; &quot; &amp;.nes']:
            with self.subTest(name=name):
                target = self.game('NES/' + name)
                decoy = self.game('NES/keep.nes')
                self.cache.write_text(f'NES/{name}\tNES f 1 2\n')
                self.assertEqual(self.run_script('shuffle.sh').returncode, 0)
                self.assertEqual(ET.parse(self.mgl).find('file').attrib['path'], str(target))
                result = self.run_script('delete.sh')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(target.exists())
                self.assertFalse(self.mgl.exists())
                self.assertEqual(decoy.read_bytes(), b'rom')


if __name__ == '__main__':
    unittest.main()

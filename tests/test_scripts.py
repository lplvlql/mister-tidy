"""Run the real scripts on temporary cards, with real curl over file:// URLs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

BASH = os.environ.get('MISTER_TEST_BASH', '/bin/bash')
SOURCE = Path(__file__).resolve().parents[1] / 'scripts'
FAMILIES = ('GBA Gameboy MegaCD MegaDrive N64 NeoGeo-CD NES NeoGeo PSX Saturn SMS SNES '
            'TGFX16 TGFX16-CD').split()
CORES = 'GBA Gameboy MegaCD MegaDrive N64 NeoGeo NES PSX Saturn SMS SNES TurboGrafx16'.split()


class Card(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='mister-tidy-test-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.card = self.base / 'card'
        self.remote = self.base / 'remote'
        self.command = self.base / 'command'
        self.command.write_text('')
        for name in ('MiSTer', 'menu.rbf'):
            self.write(self.card / name, 'old')
        self.write(self.base / 'home/keep')
        for path in SOURCE.iterdir():
            text = path.read_text().replace('/dev/MiSTer_cmd', f'"{self.command}"')
            self.write(self.card / 'scripts' / path.name, text)
            self.write(self.remote / 'scripts' / path.name, text if path.name == 'update.sh'
                       else f'#!/bin/bash\n# new {path.name}\n')
        self.outside = self.write(self.base / 'outside/keep.nes', 'outside')
        self.env = dict(os.environ, HOME=str(self.base / 'home'),
                        DIST_URL=(self.remote / 'dist.zip').as_uri(),
                        BIOS_URL=(self.remote / 'bios.json').as_uri(),
                        SCRIPTS_URL=(self.remote / 'scripts').as_uri())
        self.manifests(['menu.rbf'], ['games/NES/boot0.rom'])

    def write(self, path, text='x'):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def game(self, name):
        return self.write(self.card / 'games' / name)

    def entries(self, paths, **extra):
        out = {}
        for path in paths:
            data = self.write(self.remote / path, 'new ' + path).read_bytes()
            out[path] = dict(hash=hashlib.md5(data).hexdigest(), **extra)
        return out

    def dist(self, text):
        with zipfile.ZipFile(self.remote / 'dist.zip', 'w') as archive:
            archive.writestr('db.json', text)

    def manifests(self, dist, bios):
        """Publish both manifests; BIOS entries carry their own URLs, like the real one."""
        if not isinstance(dist, dict):
            dist = self.entries(dist)
        self.dist(json.dumps({'base_files_url': self.remote.as_uri() + '/', 'files': dist}))
        files = self.entries(bios)
        for path in files:
            files[path]['url'] = (self.remote / path).as_uri()
        self.write(self.remote / 'bios.json', json.dumps({'files': files}))

    def run_script(self, name, *args, ok=True, path=''):
        env = dict(self.env, PATH=path + os.environ['PATH'])
        result = subprocess.run([BASH, str(self.card / 'scripts' / name), *map(str, args)],
                                env=env, capture_output=True, text=True, timeout=60)
        detail = result.stdout + result.stderr
        self.assertEqual(result.returncode == 0, ok, detail)
        return detail

    def update(self, ok=True):
        # Each run installs the fixture scripts, so run the real one from the side.
        runner = self.base / 'runner.sh'
        shutil.copy(SOURCE / 'update.sh', runner)
        return self.run_script(runner, self.card, ok=ok)

    def tree(self, root):
        return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
                for p in root.rglob('*')}

    def played(self):
        return ET.parse(self.card / 'scripts/.mgl').find('file').attrib['path']


class Update(Card):
    def test_wrong_targets_are_refused_untouched(self):
        for name in ('MiSTer', 'menu.rbf'):
            self.write(self.base / 'home' / name)
        self.write(self.base / 'half/MiSTer')
        self.write(self.base / 'half2/menu.rbf')
        (self.base / 'alias').symlink_to(self.base / 'home')
        self.write(self.card / 'extra')
        fake = self.write(self.base / 'bin/grep', '#!/bin/bash\n[[ "$*" == *"$FAKE_MOUNT"*/proc/mounts ]]\n')
        fake.chmod(0o755)
        before = self.tree(self.base)
        for target in ('', '/', '///', self.base / 'home', self.base / 'alias',
                       self.base / 'half', self.base / 'half2', self.base / 'missing'):
            with self.subTest(target=target):
                self.run_script('update.sh', target, ok=False)
                self.assertEqual(self.tree(self.base), before)
        self.env['FAKE_MOUNT'] = f' {self.card}/'
        detail = self.run_script('update.sh', ok=False, path=f'{fake.parent}:')
        self.assertIn('mounted', detail)
        self.assertEqual(self.tree(self.base), before)
        for name in ('saves', 'games', 'games/NES'):
            with self.subTest(symlink=name):
                link = self.card / name
                link.parent.mkdir(exist_ok=True)
                link.symlink_to(self.outside.parent)
                self.run_script('update.sh', ok=False)
                self.assertTrue((self.card / 'extra').exists())
                link.unlink()
                if name == 'games':
                    link.mkdir()

    def test_tidy_keeps_only_allowed_content_and_is_stable(self):
        keep = ['mister.ini', 'MiSTer_alt.ini', 'Saves/NES/a.sav', 'SaveStates/a.ss', 'Config/a.cfg',
                'linux/a', 'Games/nes/a.nes', 'games/SMS/a.sms',
                'SNES_20260101.rbf', 'scripts/.shuffle', 'scripts/.mgl']
        keep += [f'games/{family}/keep' for family in FAMILIES]
        drop = ['random.txt', '.hidden', 'other.ini', '_Arcade/a.mra', 'S32X_20260101.rbf',
                'games/loose.bin', 'games/.hidden/a', 'games/S32X/a.32x', 'games/SMS/sub/a.Gg',
                'games/NEOGEO/gog-romsets.xml', 'scripts/old.sh', 'scripts/.manifest', 'scripts/.cache.tmp', 'scripts/.log']
        for name in keep + drop:
            self.write(self.card / name)
        for link in ('link', 'games/link'):
            (self.card / link).symlink_to(self.outside.parent)
        os.rename(self.card / 'MiSTer', self.card / 'mister')
        (self.remote / 'MiSTer').unlink(missing_ok=True)
        self.update()
        for name in keep + ['mister', 'menu.rbf']:
            self.assertTrue((self.card / name).exists(), name)
        for name in drop:
            self.assertFalse((self.card / name).exists(), name)
        for name in ('link', 'games/link'):
            self.assertFalse((self.card / name).is_symlink(), name)
        self.assertEqual(self.outside.read_text(), 'outside')
        before = self.tree(self.card)
        self.assertEqual(self.update(), 'updating\ndone\n')
        self.assertEqual(self.tree(self.card), before)

    def test_sync_installs_wanted_files_only(self):
        cores = [f'{family}_20261016.rbf' for family in CORES]
        for name in ('NES_20260101.rbf', 'nes_20260601.rbf'):
            self.write(self.card / name)
        wanted = ['MiSTer', 'menu.rbf', 'linux/a dir/A?B [C].txt', 'games/NES/A #100% + & café.bin']
        unwanted = ['yc.txt', '_Console/S32X_20261016.rbf', 'games/S32X/a',
                    'games/NEOGEO/gog-romsets.xml']
        self.manifests(wanted + unwanted + ['_Console/' + name for name in cores]
                       + ['_Console/NES_20250101.rbf'],
                       ['games/NEOGEO/a.rom', 'games/GAMEBOY/b.rom', 'saves/a'])
        self.update()
        for name in wanted + ['games/NeoGeo/a.rom', 'games/Gameboy/b.rom']:
            self.assertTrue((self.card / name).read_text().startswith('new '), name)
        self.assertIn('NeoGeo', os.listdir(self.card / 'games'))
        for name in unwanted + ['saves/a']:
            self.assertFalse((self.card / name).exists(), name)
        self.assertEqual(sorted(p.name for p in self.card.glob('*_*.rbf')), sorted(cores))
        for name in ('shuffle.sh', 'repeat.sh', 'delete.sh'):
            script = self.card / 'scripts' / name
            self.assertEqual(script.read_text(), f'#!/bin/bash\n# new {name}\n')
            self.assertTrue(os.access(script, os.X_OK))
        self.assertTrue(os.access(self.card / 'MiSTer', os.X_OK))

    def test_new_updater_does_everything_in_one_run(self):
        new = (SOURCE / 'update.sh').read_text().replace("'updating'", "'updating v2'")
        self.write(self.remote / 'scripts/update.sh', new)
        self.write(self.card / 'junk')
        output = self.run_script('update.sh').splitlines()
        self.assertEqual(output[2:5], ['updated: scripts/shuffle.sh', 'updated: scripts/update.sh',
                                       'updating v2'])
        self.assertIn('removed: junk', output[5:])
        self.assertEqual(output[-1], 'done')
        self.assertTrue(os.access(self.card / 'scripts/update.sh', os.X_OK))
        self.assertEqual(self.run_script('update.sh'), 'updating v2\ndone\n')
        # Without a working cmp every copy looks new; it must still finish.
        fake = self.write(self.base / 'bin/cmp', '#!/bin/bash\nexit 127\n')
        fake.chmod(0o755)
        self.assertTrue(self.run_script('update.sh', path=f'{fake.parent}:').endswith('done\n'))

    def test_update_killed_at_any_step_recovers(self):
        self.manifests(['MiSTer', 'menu.rbf', '_Console/NES_20261016.rbf'], ['games/NES/boot0.rom'])
        for name in ('Saves/a.sav', 'SaveStates/a.ss', 'Config/a.cfg', 'Games/nes/a.nes',
                     'NES_20260101.rbf', 'junk', '_Arcade/a.mra'):
            self.write(self.card / name)
        start, count = self.base / 'start', self.base / 'count'
        shutil.copytree(self.card, start)
        for tool in ('curl', 'mv', 'rm'):
            shim = self.write(self.base / 'bin' / tool, f'''#!/bin/bash
{shutil.which(tool)} "$@"; rc=$?
echo >> "{count}"
[[ $(wc -l < "{count}") -lt $KILL_AT ]] || kill -9 0
exit $rc
''')
            shim.chmod(0o755)
        env = dict(self.env, PATH=f'{self.base}/bin:' + os.environ['PATH'])
        self.update()
        final = self.tree(self.card)
        for step in range(1, 100):
            shutil.rmtree(self.card)
            shutil.copytree(start, self.card)
            count.write_text('')
            killed = subprocess.run([BASH, str(SOURCE / 'update.sh'), str(self.card)],
                                    env=dict(env, KILL_AT=str(step)), capture_output=True,
                                    start_new_session=True)
            with self.subTest(step=step):
                for name in ('saves/a.sav', 'savestates/a.ss', 'config/a.cfg', 'games/NES/a.nes'):
                    self.assertTrue((self.card / name).exists(), name)
                self.assertTrue((self.card / 'MiSTer').read_text() in ('old', 'new MiSTer'))
                self.assertTrue(list(self.card.glob('NES_*.rbf')))
                self.update()
                self.assertEqual(self.tree(self.card), final)
            if killed.returncode == 0:
                break
        self.assertTrue(10 < step < 99, step)

    def test_failed_files_keep_their_originals(self):
        paths = ['MiSTer', 'linux/a', '_Console/NES_20261016.rbf', 'games/NES/a', 'games/NES/b']
        files = self.entries(paths)
        files['MiSTer']['hash'] = '0' * 32
        files['games/NES/b']['hash'] = ''
        for name in ('linux/a', '_Console/NES_20261016.rbf'):
            (self.remote / name).unlink()
        originals = ['MiSTer', 'linux/a', 'NES_20260101.rbf', 'games/NES/b',
                     'scripts/delete.sh', 'scripts/update.sh']
        for name in originals:
            self.write(self.card / name, 'old')
        (self.remote / 'scripts/delete.sh').unlink()
        self.write(self.remote / 'scripts/update.sh', '<!DOCTYPE html>\n<html>login</html>\n')
        self.manifests(files, ['games/NES/boot0.rom'])
        self.assertIn('6 failed', self.update(ok=False))
        for name in originals:
            self.assertEqual((self.card / name).read_text(), 'old', name)
        self.assertTrue((self.card / 'games/NES/a').exists())
        self.assertEqual(list(self.card.rglob('.tmp.*')), [])

    def test_unsafe_manifest_paths_are_refused(self):
        save = self.write(self.card / 'saves/keep', 'save')
        (self.card / 'linux').mkdir()
        (self.card / 'linux/link').symlink_to(self.outside.parent)
        paths = ['games/NES/../../saves/keep', 'linux/../../outside/keep.nes', 'linux/link/keep.nes']
        files = {path: dict(hash=hashlib.md5(b'bad').hexdigest(),
                            url=self.write(self.remote / 'bad', 'bad').as_uri()) for path in paths}
        self.manifests(files, ['games/NES/boot0.rom'])
        detail = self.update(ok=False)
        for path in paths:
            self.assertIn(f'failed: {path} (unsafe path)', detail)
        self.assertEqual(save.read_text(), 'save')
        self.assertEqual(self.outside.read_text(), 'outside')

    def test_bad_manifests_block_content_but_not_scripts_or_cache(self):
        self.game('NES/a.nes')
        for kind in ('dist', 'bios'):
            for text in ('', '{', '{}', '[]', '{"files":{}}', None):
                with self.subTest(kind=kind, text=text):
                    self.manifests(['MiSTer'], ['games/NES/boot0.rom'])
                    if text is None:
                        (self.remote / ('dist.zip' if kind == 'dist' else 'bios.json')).unlink()
                    elif kind == 'dist':
                        self.dist(text)
                    else:
                        self.write(self.remote / 'bios.json', text)
                    for name in ('.cache', 'update.sh'):
                        (self.card / 'scripts' / name).unlink(missing_ok=True)
                    self.assertIn('failed: file lists', self.update(ok=False))
                    self.assertEqual((self.card / 'MiSTer').read_text(), 'old')
                    self.assertTrue((self.card / 'scripts/update.sh').exists())
                    self.assertEqual((self.card / 'scripts/.cache').read_text(), 'NES/a.nes\tNES f 1 2\n')

    def test_cache_lists_playable_games_only(self):
        want = {'Gameboy/a.GBC': 'Gameboy f 1 2', 'GBA/a.gba': 'GBA f 1 2', 'NES/a.fds': 'NES f 1 2',
                'SNES/a.sfc': 'SNES f 0 2', 'N64/a.z64': 'N64 f 1 1', 'SMS/a.sms': 'SMS f 1 1',
                'MegaDrive/a.md': 'MegaDrive f 1 1', 'MegaCD/a.cue': 'MegaCD s 0 1',
                'NeoGeo/a.neo': 'NeoGeo f 1 1', 'NeoGeo-CD/a.chd': 'NeoGeo s 1 1',
                'TGFX16/a.pce': 'TurboGrafx16 f 0 1', 'TGFX16-CD/a.cue': 'TurboGrafx16 s 1 1',
                'PSX/sub/a (Disc 1).chd': 'PSX s 0 1', 'Saturn/a.chd': 'Saturn s 0 1'}
        for name in list(want) + ['PSX/a (Disc 2).chd', 'NES/.a.nes', 'NES/a.txt', 'PSX/a.bin']:
            self.game(name)
        self.update()
        lines = (self.card / 'scripts/.cache').read_text().splitlines()
        self.assertEqual(sorted(lines), sorted(f'{k}\t{v}' for k, v in want.items()))


class Launch(Card):
    def cache(self, *names):
        self.write(self.card / 'scripts/.cache', ''.join(f'{n}\tNES f 1 2\n' for n in names))

    def test_shuffle_plays_every_existing_game_before_repeating(self):
        names = [f'NES/{i}.nes' for i in range(6)]
        games = {str(self.game(name)) for name in names}
        self.cache(*names, 'NES/missing.nes')
        picks = []
        for _ in range(12):
            self.run_script('shuffle.sh')
            picks.append(self.played())
        self.assertEqual([set(picks[:6]), set(picks[6:])], [games, games])
        entry = ET.parse(self.card / 'scripts/.mgl').find('file').attrib
        self.assertEqual((entry['type'], entry['index'], entry['delay']), ('f', '1', '2'))
        self.command.write_text('')
        self.cache('NES/missing.nes')
        self.run_script('shuffle.sh', ok=False)
        self.assertEqual(self.command.read_text(), '')

    def test_shuffle_repeat_delete_handle_odd_names(self):
        load = f'load_core {self.card}/scripts/.mgl\n'
        for name in ('NES/A [x] & B.nes', 'NES/sub/A "quoted" <B>.nes', 'NES/ $(x) &lt; &amp;.nes'):
            with self.subTest(name=name):
                target, decoy = self.game(name), self.game('NES/keep.nes')
                self.cache(name)
                self.run_script('shuffle.sh')
                self.assertEqual(self.played(), str(target))
                self.command.write_text('')
                self.run_script('repeat.sh')
                self.assertEqual(self.command.read_text(), load)
                self.run_script('delete.sh')
                self.assertFalse(target.exists())
                self.assertTrue(decoy.exists())
                self.run_script('repeat.sh', ok=False)

    def test_delete_removes_all_discs_and_tracks_only(self):
        gone = []
        for n in (1, 2):
            gone.append(self.game(f'PSX/RPG (Disc {n}).cue'))
            tracks = [f'RPG (Disc {n}) (Track {t}).bin' for t in (1, 2)]
            gone += [self.game(f'PSX/{track}') for track in tracks]
            gone[-3].write_text('\r\n'.join(f'FILE "{track}" BINARY' for track in tracks)
                                + '\r\nFILE "../../saves/a.sav" BINARY\r\n')
        keep = [self.game('PSX/RPG 2 (Disc 1).cue'), self.game('PSX/RPG 2 (Disc 1).bin'),
                self.game('PSX/Other.chd'), self.write(self.card / 'saves/a.sav')]
        ET.ElementTree(ET.Element('file', path=str(gone[0]))).write(self.card / 'scripts/.mgl')
        self.run_script('delete.sh')
        self.assertEqual([p for p in gone if p.exists()], [])
        self.assertEqual([p for p in keep if not p.exists()], [])

    def test_delete_refuses_anything_outside_games(self):
        games = self.card / 'games'
        games.mkdir()
        (games / 'link').symlink_to(self.outside.parent)
        (games / 'link.nes').symlink_to(self.outside)
        save = self.write(self.card / 'saves/a.sav')
        sibling = self.write(self.card / 'games2/a.nes')
        for path in ('', games, self.outside, save, sibling, games / '../saves/a.sav',
                     games / 'link/keep.nes', games / 'link.nes'):
            with self.subTest(path=path):
                ET.ElementTree(ET.Element('file', path=str(path))).write(self.card / 'scripts/.mgl')
                self.run_script('delete.sh', ok=False)
                self.assertTrue(save.exists() and sibling.exists() and self.outside.exists())
                self.assertTrue((games / 'link.nes').is_symlink())


if __name__ == '__main__':
    unittest.main()

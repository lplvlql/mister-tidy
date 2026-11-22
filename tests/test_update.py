"""Offline update fixtures: fake curl, real manifests, hashes and Bash 3.2."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

BASH = os.environ.get('MISTER_TEST_BASH', '/bin/bash')
SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/update.sh'
UPDATE = SCRIPT


def run_stage(stage, card, env):
    """Source update.sh (its guard skips main) and run one stage on a card."""
    return subprocess.run([BASH, '-c', 'source "$1" "$2"; ' + stage, 'run-stage', str(UPDATE), str(card)],
                          env=env, capture_output=True, text=True)


class UpdateFailures(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mister-update-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.card = self.base / 'card'
        self.card.mkdir()
        for marker in ('MiSTer', 'menu.rbf'):
            (self.card / marker).write_bytes(b'card marker')
        self.home = self.base / 'home'
        self.home.mkdir()
        self.payload = self.base / 'payload'
        self.payload.mkdir()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.log = self.base / 'log'
        fake = self.bin / 'curl'
        fake.write_text('#!' + sys.executable + '\n' + '''
import os, pathlib, sys
from urllib.parse import unquote
args = sys.argv[1:]
url = next(a for a in args if a.startswith('file://'))
path = pathlib.Path(unquote(url[7:]))
out = pathlib.Path(args[args.index('-o') + 1]) if '-o' in args else None
rel = str(path.relative_to(pathlib.Path(os.environ['PAYLOAD'])))
data = path.read_bytes()
if out:
    out.write_bytes(b'partial' if rel in os.environ.get('FAIL_URLS', '').split(',') else data)
else:
    sys.stdout.buffer.write(data)
if rel in os.environ.get('FAIL_URLS', '').split(','):
    sys.exit(22)
''')
        fake.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin) + ':' + os.environ['PATH'],
                        PAYLOAD=str(self.payload), MISTER_TIDY_LOG_FILE=str(self.log),
                        DIST_URL=(self.payload / 'dist.json').as_uri(),
                        BIOS_URL=(self.payload / 'bios.json').as_uri(),
                        SCRIPTS_URL=(self.payload / 'scripts').as_uri())

    def manifest(self, name, paths, bad_hashes=()):
        files = {}
        for path in paths:
            dest = self.payload / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(('new: ' + path).encode())
            files[path] = {'hash': hashlib.md5(dest.read_bytes()).hexdigest()}
            if path in bad_hashes:
                files[path]['hash'] = '0' * 32
        (self.payload / name).write_text(json.dumps({
            'base_files_url': self.payload.as_uri() + '/', 'files': files}))

    def scripts(self):
        for name in ('delete.sh', 'repeat.sh', 'shuffle.sh', 'update.sh'):
            dest = self.payload / 'scripts' / name
            dest.parent.mkdir(exist_ok=True)
            dest.write_text('#!/bin/bash\n# fixture\n')

    def run_update(self):
        return subprocess.run([BASH, str(SCRIPT), str(self.card)],
                              env=self.env, capture_output=True, text=True)

    def test_update_installs_scripts_and_builds_cache(self):
        self.manifest('dist.json', {})
        self.manifest('bios.json', {})
        self.scripts()
        (self.card / 'games/NES').mkdir(parents=True)
        (self.card / 'games/NES/a.nes').write_bytes(b'rom')
        result = self.run_update()
        self.assertEqual(result.returncode, 0, self.log.read_text())
        scripts = self.card / 'scripts'
        self.assertEqual({path.name for path in scripts.iterdir() if not path.name.startswith('.')},
                         {'update.sh', 'shuffle.sh', 'repeat.sh', 'delete.sh'})
        self.assertEqual((scripts / '.cache').read_text(), 'NES/a.nes\tNES f 1 2\n')

    def test_invalid_update_targets_refuse_before_writes_or_downloads(self):
        wrong = self.base / 'wrong'
        wrong.mkdir()
        (wrong / 'MiSTer').write_bytes(b'unrelated file')
        empty = self.base / 'empty'
        empty.mkdir()
        for name in ('MiSTer', 'menu.rbf'):
            (self.home / name).write_bytes(b'home marker')
        alias = self.base / 'home-alias'
        alias.symlink_to(self.home, target_is_directory=True)
        before = {str(p.relative_to(self.base)): p.read_bytes()
                  for p in self.base.rglob('*') if p.is_file()}
        for target in ('', '/', '///', self.home, alias, wrong, empty, self.base / 'missing'):
            with self.subTest(target=target):
                result = subprocess.run([BASH, str(SCRIPT), str(target)], env=self.env,
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                after = {str(p.relative_to(self.base)): p.read_bytes()
                         for p in self.base.rglob('*') if p.is_file()}
                self.assertEqual(after, before)
                self.assertFalse(self.log.exists())
                self.assertFalse((wrong / 'scripts').exists())
                self.assertFalse((self.home / 'scripts').exists())

    def test_all_sync_callers_count_failures_and_preserve_originals(self):
        self.manifest('dist.json', ['MiSTer', 'linux/test', '_Console/NES_20261016.rbf',
                                   'games/NES/support'], ['MiSTer', 'games/NES/support'])
        self.manifest('bios.json', ['games/NES/hashbios', 'games/NES/rawbios'],
                      ['games/NES/hashbios'])
        bios = json.loads((self.payload / 'bios.json').read_text())
        bios['files']['games/NES/rawbios']['hash'] = ''
        (self.payload / 'bios.json').write_text(json.dumps(bios))
        self.scripts()
        self.env['FAIL_URLS'] = 'linux/test,_Console/NES_20261016.rbf,games/NES/rawbios,scripts/delete.sh'
        for name in ('MiSTer', 'linux/test', 'NES_20261016.rbf', 'games/NES/support',
                     'games/NES/hashbios', 'scripts/delete.sh'):
            dest = self.card / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b'original')
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        log = self.log.read_text()
        for name, reason in [('MiSTer', 'checksum mismatch'), ('linux/test', 'download failed'),
                             ('NES_20261016.rbf', 'download failed'),
                             ('games/NES/support', 'checksum mismatch'),
                             ('games/NES/hashbios', 'checksum mismatch'),
                             ('games/NES/rawbios', 'download failed'),
                             ('scripts/delete.sh', 'download failed')]:
            self.assertIn(f'failed: {name} ({reason})', log)
            self.assertNotIn(f'unchanged: {name}\n', log)
            self.assertNotIn(f'copied: {name}\n', log)
            dest = self.card / name
            if name != 'games/NES/rawbios':
                self.assertEqual(dest.read_bytes(), b'original')
            else:
                self.assertFalse(dest.exists())
        self.assertIn('update failed: 7 failure(s)', log)
        self.assertIn('copied: scripts/update.sh', log)
        self.assertEqual(list(self.card.rglob('*.tmp.*')), [])

    def test_success_then_true_hash_match(self):
        self.manifest('dist.json', ['MiSTer'])
        self.manifest('bios.json', ['games/NES/bios'])
        self.scripts()
        self.assertEqual(self.run_update().returncode, 0)
        self.log.write_text('')
        self.assertEqual(self.run_update().returncode, 0)
        log = self.log.read_text()
        self.assertIn('unchanged: MiSTer', log)
        self.assertIn('unchanged: games/NES/bios', log)
        self.assertNotIn('failed:', log)
        self.assertEqual(list(self.card.rglob('*.tmp.*')), [])

    def test_newer_core_replaces_older_dated_versions(self):
        (self.card / 'NES_20260101.rbf').write_bytes(b'old')
        (self.card / 'NES_20260601.rbf').write_bytes(b'older')
        (self.card / 'SNES_20260101.rbf').write_bytes(b'other family')
        self.manifest('dist.json', ['_Console/NES_20261016.rbf'])
        self.manifest('bios.json', [])
        self.scripts()
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(sorted(p.name for p in self.card.glob('NES_*.rbf')), ['NES_20261016.rbf'])
        self.assertTrue((self.card / 'SNES_20260101.rbf').exists())
        self.env['FAIL_URLS'] = '_Console/NES_20261101.rbf'
        self.manifest('dist.json', ['_Console/NES_20261101.rbf'])
        self.run_update()
        self.assertTrue((self.card / 'NES_20261016.rbf').exists())

    def test_manifest_with_per_file_urls_and_no_base_url(self):
        self.manifest('dist.json', ['MiSTer'])
        src = self.payload / 'mirror/boot.rom'
        src.parent.mkdir(parents=True)
        src.write_bytes(b'bios bytes')
        (self.payload / 'bios.json').write_text(json.dumps({'db_id': 'bios_db', 'files': {
            'games/PSX/boot.rom': {'hash': hashlib.md5(b'bios bytes').hexdigest(), 'url': src.as_uri()}}}))
        self.scripts()
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.card / 'games/PSX/boot.rom').read_bytes(), b'bios bytes')

    def test_removed_platforms_are_not_synced(self):
        self.manifest('dist.json', ['_Console/S32X_20261016.rbf',
                                   'games/S32X/support', 'games/NeoGeoPocket/support', 'games/SMS/game.GG',
                                   'games/SMS/keep.sms'])
        self.manifest('bios.json', ['games/S32X/bios', 'games/NeoGeoPocket/bios', 'games/SMS/bios.gG',
                                   'games/SMS/keepbios'])
        self.scripts()
        result = self.run_update()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.card / 'games/S32X').exists())
        self.assertFalse((self.card / 'games/NeoGeoPocket').exists())
        self.assertFalse((self.card / 'S32X_20261016.rbf').exists())
        self.assertFalse((self.card / 'games/SMS/game.GG').exists())
        self.assertFalse((self.card / 'games/SMS/bios.gG').exists())
        self.assertTrue((self.card / 'games/SMS/keep.sms').exists())
        self.assertTrue((self.card / 'games/SMS/keepbios').exists())

    def test_script_permissions_on_copied_unchanged_and_failed(self):
        # The current no-hash script sync always copies; exercise its unchanged
        # contract explicitly so future hash-aware sync preserves executable bits.
        scripts = self.card / 'scripts'
        scripts.mkdir()
        for name in ('copied', 'unchanged', 'failed'):
            dest = scripts / name
            dest.write_text('fixture')
            dest.chmod(0o644)
        stub = ('source "$1" "$2"\nSCRIPTS_FILES=(copied unchanged failed)\n'
                'sync_download() {\n  case "$1" in\n    scripts/copied) return 0 ;;\n'
                '    scripts/unchanged) return 1 ;;\n    scripts/failed) return 2 ;;\n  esac\n}\nsync_scripts\n')
        result = subprocess.run([BASH, '-c', stub, 'fixture', str(SCRIPT), str(self.card)],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('copied', 'unchanged'):
            self.assertEqual((scripts / name).stat().st_mode & 0o111, 0o111)
        self.assertFalse((scripts / 'failed').stat().st_mode & 0o111)

    def test_invalid_manifest_structure_aborts_before_content_sync(self):
        valid_base = self.payload.as_uri() + '/'
        invalid = [
            '', '{', '{}', 'null', '[]',
            json.dumps({'base_files_url': valid_base}),
            json.dumps({'base_files_url': valid_base, 'files': None}),
            json.dumps({'base_files_url': valid_base, 'files': []}),
            json.dumps({'base_files_url': '', 'files': {}}),
            json.dumps({'base_files_url': 1, 'files': {}}),
            json.dumps({'base_files_url': valid_base, 'files': {'MiSTer': None}}),
            json.dumps({'base_files_url': valid_base, 'files': {'MiSTer': {'hash': 7}}}),
            '{"files":{},"base_files_url":"file:///"}\n{}',
        ]
        for manifest_name, label in [('dist.json', 'distribution'), ('bios.json', 'BIOS')]:
            for text in invalid:
                with self.subTest(manifest=manifest_name, text=text):
                    self.manifest('dist.json', ['MiSTer'])
                    self.manifest('bios.json', [])
                    (self.payload / manifest_name).write_text(text)
                    marker_file = self.card / 'MiSTer'
                    marker_file.write_bytes(b'original')
                    self.log.write_text('')
                    result = self.run_update()
                    self.assertNotEqual(result.returncode, 0)
                    log = self.log.read_text()
                    self.assertIn(f'failed: {label} manifest (invalid JSON or structure)', log)
                    self.assertNotIn('stage: root', log)
                    self.assertNotIn('stage: scripts', log)
                    self.assertEqual(marker_file.read_bytes(), b'original')

    def test_zip_manifest_reads_complete_compact_and_multiline_json(self):
        self.manifest('dist.json', ['MiSTer', 'games/NES/support'])
        self.manifest('bios.json', [])
        self.scripts()
        manifest = json.loads((self.payload / 'dist.json').read_text())
        archive = self.payload / 'dist.zip'
        self.env['DIST_URL'] = archive.as_uri()
        for indent in (None, 2):
            with self.subTest(indent=indent):
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('db.json', json.dumps(manifest, indent=indent))
                result = self.run_update()
                self.assertEqual(result.returncode, 0, self.log.read_text())
                self.assertEqual((self.card / 'MiSTer').read_bytes(),
                                 (self.payload / 'MiSTer').read_bytes())
                self.assertEqual((self.card / 'games/NES/support').read_bytes(),
                                 (self.payload / 'games/NES/support').read_bytes())
                (self.card / 'MiSTer').write_bytes(b'card marker')
                (self.card / 'games/NES/support').unlink()

    def test_zip_with_multiple_json_documents_is_rejected(self):
        self.manifest('dist.json', [])
        doc = (self.payload / 'dist.json').read_text()
        archive = self.payload / 'dist.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('one.json', doc)
            z.writestr('two.json', doc)
        self.env['DIST_URL'] = archive.as_uri()
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assertIn('failed: distribution manifest (invalid JSON or structure)',
                      self.log.read_text())

    def test_traversal_paths_are_rejected_without_touching_saves(self):
        self.manifest('dist.json', [])
        self.manifest('bios.json', [])
        self.scripts()
        save = self.card / 'saves/keep'
        save.parent.mkdir()
        save.write_bytes(b'original save')
        outside = self.base / 'keep'
        outside.write_bytes(b'outside card')
        for manifest_name, key in [
            ('dist.json', 'games/NES/../../saves/keep'),
            ('dist.json', 'linux/../saves/keep'),
            ('dist.json', 'linux/../../keep'),
            ('bios.json', 'games/NES/../../saves/keep'),
        ]:
            with self.subTest(manifest=manifest_name, key=key):
                self.manifest('dist.json', [])
                self.manifest('bios.json', [])
                (self.payload / manifest_name).write_text(json.dumps({
                    'base_files_url': self.payload.as_uri() + '/',
                    'files': {key: {'hash': ''}}}))
                result = self.run_update()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'failed: {key} (unsafe destination)', self.log.read_text())
                self.assertEqual(save.read_bytes(), b'original save')
                self.assertEqual(outside.read_bytes(), b'outside card')

    def test_symlink_destinations_are_rejected(self):
        self.manifest('dist.json', ['games/NES/link/keep', 'linux/link/keep'])
        self.manifest('bios.json', ['games/NES/link/bios'])
        self.scripts()
        outside = self.base / 'outside'
        outside.mkdir()
        for name in ('keep', 'bios'):
            (outside / name).write_bytes(b'outside')
        for name in ('games/NES/link', 'linux/link'):
            link = self.card / name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(self.run_update().returncode, 0)
        for name in ('keep', 'bios'):
            self.assertEqual((outside / name).read_bytes(), b'outside')
        log = self.log.read_text()
        for name in ('games/NES/link/keep', 'linux/link/keep', 'games/NES/link/bios'):
            self.assertIn(f'failed: {name} (unsafe destination)', log)

    def test_symlink_family_root_refused_before_writes(self):
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'keep').write_bytes(b'outside')
        (self.card / 'linux').symlink_to(outside, target_is_directory=True)
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assertEqual((outside / 'keep').read_bytes(), b'outside')
        self.assertEqual(list(outside.iterdir()), [outside / 'keep'])

    def test_real_offline_curl_handles_encoded_path_components(self):
        # Real curl uses file:// only; this verifies URL syntax beyond the stub.
        paths = ['games/NES/A B #100% + & café.bin',
                 'linux/nested dir/A?B [C].txt']
        self.manifest('dist.json', paths)
        self.manifest('bios.json', ['games/NES/BIOS #1.bin'])
        self.scripts()
        self.env['PATH'] = os.environ['PATH']
        result = self.run_update()
        self.assertEqual(result.returncode, 0, self.log.read_text())
        for path in paths + ['games/NES/BIOS #1.bin']:
            self.assertEqual((self.card / path).read_bytes(), (self.payload / path).read_bytes())

    def test_game_and_bios_sync_skip_blacklist_exact_and_descendant_paths(self):
        banned = ['Gameboy/Palettes', 'NES/Palettes', 'PSX/240p Test Suite',
                  'PSX/PadTest 1.1', 'SNES/240p Test Suite',
                  'MegaDrive/240p Test Suite.bin', 'N64/N64 Controller Tester.z64',
                  'NeoGeo/gog-romsets.xml', 'NeoGeo/gog-broken-romsets.xml']
        self.scripts()
        for manifest_name in ('dist.json', 'bios.json'):
            with self.subTest(manifest=manifest_name):
                self.manifest('dist.json', [])
                self.manifest('bios.json', [])
                files = {'games/' + path: {'hash': ''} for path in banned}
                files.update({'games/' + path + '/child.bin': {'hash': ''} for path in banned})
                keep = 'games/NES/PalettesExtra/keep.bin'
                source = self.payload / keep
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b'allowed sibling')
                files[keep] = {'hash': ''}
                (self.payload / manifest_name).write_text(json.dumps({
                    'base_files_url': self.payload.as_uri() + '/', 'files': files}))
                result = self.run_update()
                self.assertEqual(result.returncode, 0, self.log.read_text())
                for path in banned:
                    self.assertFalse((self.card / 'games' / path).exists())
                self.assertEqual((self.card / keep).read_bytes(), b'allowed sibling')

    def test_download_preserves_modes_and_mister_is_executable(self):
        self.manifest('dist.json', ['MiSTer', 'menu.rbf', 'linux/tool', 'games/NES/new.bin'])
        self.manifest('bios.json', [])
        self.scripts()
        for name, mode in [('MiSTer', 0o755), ('menu.rbf', 0o640), ('linux/tool', 0o710)]:
            dest = self.card / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b'original')
            dest.chmod(mode)
        self.assertEqual(self.run_update().returncode, 0, self.log.read_text())
        for name, mode in [('MiSTer', 0o755), ('menu.rbf', 0o640), ('linux/tool', 0o710),
                           ('games/NES/new.bin', 0o644)]:
            self.assertEqual((self.card / name).stat().st_mode & 0o7777, mode)
        for script in (self.card / 'scripts').glob('*.sh'):
            self.assertEqual(script.stat().st_mode & 0o111, 0o111)
        # Matching content must still repair a missing executable bit.
        (self.card / 'MiSTer').chmod(0o644)
        self.assertEqual(self.run_update().returncode, 0, self.log.read_text())
        self.assertEqual((self.card / 'MiSTer').stat().st_mode & 0o111, 0o111)
        # Replacing an empty card marker must also yield an executable binary.
        (self.card / 'MiSTer').write_bytes(b'')
        self.assertEqual(self.run_update().returncode, 0, self.log.read_text())
        self.assertEqual((self.card / 'MiSTer').stat().st_mode & 0o111, 0o111)

    def test_mode_setting_failure_preserves_previous_destination(self):
        self.manifest('dist.json', ['MiSTer'])
        self.manifest('bios.json', [])
        self.scripts()
        dest = self.card / 'MiSTer'
        dest.write_bytes(b'original')
        dest.chmod(0o755)
        chmod = self.bin / 'chmod'
        chmod.write_text('#!/bin/bash\ncase "$2" in */MiSTer.tmp.*) exit 1 ;; esac\nexec /bin/chmod "$@"\n')
        chmod.chmod(0o755)
        self.assertNotEqual(self.run_update().returncode, 0)
        self.assertEqual(dest.read_bytes(), b'original')
        self.assertEqual(dest.stat().st_mode & 0o777, 0o755)
        self.assertIn('failed: MiSTer (local file operation failed)', self.log.read_text())
        self.assertEqual(list(self.card.rglob('*.tmp.*')), [])

    def test_unhashed_distribution_files_update_but_existing_bios_is_preserved(self):
        for manifest, rel in [('dist.json', 'games/NES/support.bin'),
                              ('bios.json', 'games/NES/bios.bin')]:
            self.manifest(manifest, [rel])
            path = self.payload / manifest
            doc = json.loads(path.read_text())
            doc['files'][rel]['hash'] = ''
            path.write_text(json.dumps(doc))
            dest = self.card / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b'existing')
        self.scripts()
        self.assertEqual(self.run_update().returncode, 0, self.log.read_text())
        self.assertEqual((self.card / 'games/NES/support.bin').read_bytes(),
                         (self.payload / 'games/NES/support.bin').read_bytes())
        self.assertEqual((self.card / 'games/NES/bios.bin').read_bytes(), b'existing')

    def test_failed_manifest_aborts_and_cleans_partial_download(self):
        self.manifest('dist.json', [])
        self.env['FAIL_URLS'] = 'dist.json'
        result = self.run_update()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('failed: distribution manifest', self.log.read_text())
        self.assertFalse((self.card / 'scripts/.manifest').exists())
        self.assertFalse((self.card / 'scripts/.manifest.tmp').exists())


class CacheSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mister-cache-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.card = self.base / 'card'
        self.card.mkdir()
        for marker in ('MiSTer', 'menu.rbf'):
            (self.card / marker).write_bytes(b'card marker')
        self.cache = self.base / 'cache'
        self.cache.write_text('NES/previous.nes\tNES f 1 2\n')
        self.env = dict(os.environ, CACHE_FILE=str(self.cache),
                        MISTER_TIDY_LOG_FILE=str(self.base / 'log'))

    def run_cache(self):
        return run_stage('build_cache', self.card, self.env)

    def assert_preserved(self):
        self.assertEqual(self.cache.read_text(), 'NES/previous.nes\tNES f 1 2\n')
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
        self.assertEqual(self.cache.read_text(), 'NES/keep.nes\tNES f 1 2\n')
        self.assertEqual(list(self.base.glob('cache.*')), [])


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
        return run_stage('clean_card', target, self.env)

    def snapshot(self, root):
        return {str(p.relative_to(root)): p.read_bytes()
                for p in root.rglob('*') if p.is_file()}

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
        before = (self.snapshot(a), self.snapshot(b))
        result = subprocess.run([BASH, '-c', 'source "$1" "$2"; move_or_rename "$3" "$4"',
                                 'fixture', str(UPDATE), str(self.card), str(a), str(b)],
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.snapshot(a), self.snapshot(b)), before)


if __name__ == '__main__':
    unittest.main()

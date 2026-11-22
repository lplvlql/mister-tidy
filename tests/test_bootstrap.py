"""Bootstrap target checks and migration with local payloads only."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
BASH = os.environ.get('MISTER_TEST_BASH', '/bin/bash')


class BootstrapSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='mister-bootstrap-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.card('home')
        self.payload = self.base / 'payload/scripts'
        self.payload.mkdir(parents=True)
        for name in ('delete.sh', 'repeat.sh', 'shuffle.sh'):
            (self.payload / name).write_text('#!/bin/bash\nexit 0\n')
        # The installer runs update.sh --clean; run only the real clean stage offline.
        (self.payload / 'update.sh').write_text(
            f'#!/bin/bash\nsource "{REPO / "scripts/update.sh"}" "$@"\nclean_card\n')
        self.env = dict(os.environ, HOME=str(self.home),
                        REPO_BASE_URL=self.payload.parent.as_uri())

    def card(self, name):
        card = self.base / name
        scripts = card / 'scripts'
        scripts.mkdir(parents=True)
        for marker in ('MiSTer', 'menu.rbf'):
            (card / marker).write_bytes(b'marker')
        (scripts / 'personal.sh').write_bytes(b'personal helper')
        (scripts / 'mister-tidy.sh').write_bytes((REPO / 'mister-tidy.sh').read_bytes())
        return card

    def run_bootstrap(self, target):
        return subprocess.run([BASH, str(REPO / 'mister-tidy.sh'), str(target)],
                              env=self.env, capture_output=True, text=True)

    def snapshot(self):
        return {str(p.relative_to(self.base)): p.read_bytes()
                for p in self.base.rglob('*') if p.is_file()}

    def test_invalid_targets_have_no_filesystem_side_effects(self):
        wrong = self.base / 'wrong'
        wrong.mkdir()
        (wrong / 'keep').write_bytes(b'keep')
        alias = self.base / 'home-alias'
        alias.symlink_to(self.home, target_is_directory=True)
        before = self.snapshot()
        for target in ('', '/', '///', self.home, alias, wrong, self.base / 'missing'):
            with self.subTest(target=target):
                result = self.run_bootstrap(target)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.snapshot(), before)

    def test_external_scripts_symlink_refused_before_installation(self):
        card = self.base / 'card'
        card.mkdir()
        for marker in ('MiSTer', 'menu.rbf'):
            (card / marker).write_bytes(b'marker')
        (card / 'scripts').symlink_to(self.home / 'scripts', target_is_directory=True)
        before = self.snapshot()
        self.assertNotEqual(self.run_bootstrap(card).returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_clean_preflight_rejection_preserves_personal_helpers(self):
        card = self.card('card')
        outside = self.base / 'outside'
        outside.mkdir()
        (card / 'games').symlink_to(outside, target_is_directory=True)
        result = self.run_bootstrap(card)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((card / 'scripts/personal.sh').read_bytes(), b'personal helper')
        self.assertTrue((card / 'scripts/mister-tidy.sh').exists())

    def test_failed_update_preserves_bootstrap(self):
        card = self.card('card')
        (self.payload / 'update.sh').write_text('#!/bin/bash\nexit 9\n')
        before = (card / 'scripts/mister-tidy.sh').read_bytes()
        result = self.run_bootstrap(card)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((card / 'scripts/mister-tidy.sh').read_bytes(), before)

    def test_failed_payload_fetch_preserves_script_and_removes_temp(self):
        card = self.card('card')
        original = card / 'scripts/delete.sh'
        original.write_bytes(b'original delete script')
        (self.payload / 'delete.sh').unlink()
        self.assertNotEqual(self.run_bootstrap(card).returncode, 0)
        self.assertEqual(original.read_bytes(), b'original delete script')
        self.assertEqual(list((card / 'scripts').glob('*.tmp.*')), [])

    def test_earlier_helper_stays_executable_when_later_fetch_fails(self):
        card = self.card('card')
        (self.payload / 'update.sh').unlink()
        self.assertNotEqual(self.run_bootstrap(card).returncode, 0)
        helper = card / 'scripts/delete.sh'
        self.assertEqual(helper.read_bytes(), (self.payload / 'delete.sh').read_bytes())
        self.assertEqual(helper.stat().st_mode & 0o777, 0o755)
        self.assertTrue((card / 'scripts/mister-tidy.sh').exists())
        self.assertEqual(list((card / 'scripts').glob('*.tmp.*')), [])

    def test_valid_local_migration_still_completes(self):
        card = self.card('card')
        result = self.run_bootstrap(card)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('migration complete', result.stdout)
        self.assertFalse((card / 'scripts/personal.sh').exists())
        self.assertFalse((card / 'scripts/mister-tidy.sh').exists())
        self.assertTrue((card / 'scripts/update.sh').exists())
        for script in (card / 'scripts').glob('*.sh'):
            self.assertEqual(script.stat().st_mode & 0o111, 0o111)


if __name__ == '__main__':
    unittest.main()

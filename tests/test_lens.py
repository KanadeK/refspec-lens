import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from refspec_lens.cli import main
from refspec_lens.core import InputError, Rule, explain, match, snapshot, valid_ref

A = 'a' * 40
B = 'b' * 40
FETCH = '+refs/heads/*:refs/remotes/origin/*'


class UnitTests(unittest.TestCase):
    def test_snapshot_bom_crlf_unicode(self):
        self.assertEqual(snapshot('\ufeff' + A + '\trefs/heads/配置\r\n'), {'refs/heads/配置': A})
        name = 'refs/heads/a\u00a0b\u2028c'
        self.assertEqual(snapshot(A + '\t' + name), {name: A})

    def test_reject_bad_snapshots(self):
        for value in ['oops', '0' * 40 + ' refs/heads/a', A + ' HEAD',
                      A + ' refs/tags/a^{}', A + ' refs/heads/a b',
                      A + ' refs/heads/a\n' + A + ' refs/heads/a',
                      A + ' refs/heads/a\n' + 'b' * 64 + ' refs/heads/b']:
            with self.subTest(value=value), self.assertRaises(InputError):
                snapshot(value)

    def test_ref_validation(self):
        for value in ['refs/a', 'refs/heads/a.b', 'refs/heads/a./b', 'refs/heads/配置']:
            self.assertTrue(valid_ref(value), value)
        for value in ['heads/a', 'refs/a..b', 'refs/.a', 'refs/a.lock/b', 'refs/a@{x',
                      'refs/a\\b', 'refs/a.', 'refs/a//b', 'refs/a b']:
            self.assertFalse(valid_ref(value), value)

    def test_glob_matches_slashes_and_suffix(self):
        self.assertEqual(match('refs/heads/pre*-end', 'refs/heads/prea/b-end'), 'a/b')
        self.assertEqual(match('abc*xyz', 'abcxyz'), '')
        self.assertIsNone(match('abc*xyz', 'abcxy'))

    def test_rule_rejections(self):
        for spec in ['HEAD:refs/a', 'refs/a', '^refs/a:refs/b', '+^refs/a',
                     'refs/*:refs/b', 'refs/**:refs/**', 'refs/a:', ':refs/a',
                     'refs/a:refs/a*', 'refs/a:refs/.bad']:
            with self.subTest(spec=spec), self.assertRaises(InputError):
                Rule.parse(spec, 1)

    def test_mapped_excluded_unmatched(self):
        report = explain({'refs/heads/main': A, 'refs/heads/tmp/x': B, 'refs/tags/v1': A},
                         {}, [FETCH, '^refs/heads/tmp/*'])
        self.assertEqual([r['state'] for r in report['sources']], ['mapped', 'excluded', 'unmatched'])
        self.assertEqual(report['mappings'][0]['destination'], 'refs/remotes/origin/main')

    def test_duplicate_rule_retains_provenance(self):
        report = explain({'refs/heads/main': A}, {}, [FETCH, FETCH])
        self.assertEqual(report['mappings'][0]['rules'], [1, 2])
        self.assertFalse(report['conflicts'])

    def test_conflicting_sources_same_oid(self):
        report = explain({'refs/heads/a': A, 'refs/heads/b': A}, {},
                         ['refs/heads/a:refs/cache/x', 'refs/heads/b:refs/cache/x'])
        self.assertEqual(report['conflicts'][0]['kind'], 'multiple-sources')

    def test_destination_prefix_collision(self):
        report = explain({'refs/heads/a': A, 'refs/heads/b': B}, {},
                         ['refs/heads/a:refs/cache/x', 'refs/heads/b:refs/cache/x/y'])
        self.assertEqual(report['conflicts'][0]['kind'], 'file-directory')

    def test_local_scope_and_negative_protection(self):
        local = {'refs/remotes/origin/main': B, 'refs/remotes/origin/old': A,
                 'refs/remotes/origin/keep': A, 'refs/heads/main': B}
        report = explain({'refs/heads/main': A}, local, [FETCH, '^refs/heads/keep'])
        self.assertEqual(report['prune_candidates'], ['refs/remotes/origin/old'])
        self.assertEqual(report['mappings'][0]['state'], 'different')

    def test_tag_pruning_exposure(self):
        report = explain({}, {'refs/tags/private': A}, ['refs/tags/*:refs/tags/*'])
        self.assertEqual(report['prune_candidates'], ['refs/tags/private'])

    def test_missing_exact_ref(self):
        self.assertEqual(explain({}, {}, ['refs/heads/absent:refs/cache/x'])[
            'missing_exact_rules'], [1])

    def test_all_negative_invalid(self):
        with self.assertRaises(InputError):
            explain({}, {}, ['^refs/heads/a'])

    def test_snapshot_and_rule_limits(self):
        with self.assertRaises(InputError):
            snapshot(A + ' refs/a\n' + B + ' refs/b', 1)
        with self.assertRaises(InputError):
            explain({}, {}, [FETCH] * 129)

    def test_mixed_snapshot_formats(self):
        with self.assertRaises(InputError):
            explain({'refs/heads/a': A}, {'refs/cache/a': 'b' * 64}, [FETCH])

    def test_sha256(self):
        r = snapshot('f' * 64 + ' refs/heads/a')
        self.assertEqual(explain(r, {}, [FETCH])['mappings'][0]['oid'], 'f' * 64)

    def test_cli_exit_codes_and_no_input_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            remote, local = Path(tmp) / 'remote.txt', Path(tmp) / 'local.txt'
            remote.write_text(A + ' refs/heads/main\n', encoding='utf-8')
            local.write_text(A + ' refs/remotes/origin/old\n', encoding='utf-8')
            before = remote.read_bytes(), local.read_bytes()
            base = ['--remote', str(remote), '--local', str(local), '--refspec', FETCH, '--json']
            for extra, expected in [([], 0), (['--prune'], 1), (['--max-bytes', '1'], 2)]:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(base + extra), expected)
                self.assertIn('schema_version', json.loads(output.getvalue()))
            self.assertEqual(before, (remote.read_bytes(), local.read_bytes()))

    def test_prune_requires_local(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['--remote', 'unused', '--refspec', FETCH, '--prune']), 2)


class NativeGitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='refspec-lens-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote, self.local = self.root / 'remote', self.root / 'local'
        for repo in (self.remote, self.local):
            repo.mkdir()
            self.git(repo, '-c', 'init.templateDir=', 'init', '-q', '-b', 'main')
            self.git(repo, 'config', 'user.name', 'KanadeK')
            self.git(repo, 'config', 'user.email', '121669563+KanadeK@users.noreply.github.com')
        (self.remote / 'file').write_bytes(b'fixture')
        self.git(self.remote, 'add', 'file')
        self.git(self.remote, 'commit', '-qm', 'Fixture')
        for branch in ('topic/one', 'private/one'):
            self.git(self.remote, 'branch', branch)
        self.git(self.remote, 'tag', 'v1')

    def git(self, repo, *args, check=True):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(['git', '-C', str(repo), '-c', 'core.hooksPath=' + os.devnull,
                               *args], check=check, env=env, capture_output=True,
                              text=True, encoding='utf-8')

    def refs(self, repo):
        return snapshot(self.git(repo, 'for-each-ref', '--format=%(objectname) %(refname)').stdout)

    def test_mapping_matches_actual_fetch(self):
        specs = [FETCH, '^refs/heads/private/*', 'refs/tags/*:refs/tags/*']
        report = explain(self.refs(self.remote), {}, specs)
        self.git(self.local, 'fetch', '--no-tags', str(self.remote), *specs)
        expected = {item['destination']: item['oid'] for item in report['mappings']}
        self.assertEqual(self.refs(self.local), expected)

    def test_pruning_matches_git_and_preserves_negative(self):
        specs = [FETCH, '^refs/heads/private/*', 'refs/tags/*:refs/tags/*']
        self.git(self.local, 'fetch', '--no-tags', str(self.remote), FETCH)
        oid = self.git(self.remote, 'rev-parse', 'HEAD').stdout.strip()
        for ref in ['refs/remotes/origin/deleted', 'refs/tags/local-only']:
            self.git(self.local, 'update-ref', ref, oid)
        self.git(self.remote, 'branch', '-D', 'private/one')
        before = self.refs(self.local)
        report = explain(self.refs(self.remote), before, specs)
        self.git(self.local, 'fetch', '--no-tags', '--prune', str(self.remote), *specs)
        actual_deleted = sorted(set(before) - set(self.refs(self.local)))
        self.assertEqual(report['prune_candidates'], actual_deleted)
        self.assertIn('refs/remotes/origin/private/one', self.refs(self.local))

    def test_conflicting_mapping_is_rejected_by_git(self):
        specs = ['refs/heads/main:refs/cache/same', 'refs/heads/topic/one:refs/cache/same']
        self.assertTrue(explain(self.refs(self.remote), {}, specs)['conflicts'])
        actual = self.git(self.local, 'fetch', '--no-tags', str(self.remote), *specs, check=False)
        self.assertNotEqual(actual.returncode, 0)

    def test_ref_validator_against_git(self):
        for ref in ['refs/a', 'refs/heads/a./b', 'refs/heads/配置', 'refs/a.lock/b', 'refs/a..b']:
            actual = self.git(self.local, 'check-ref-format', ref, check=False)
            self.assertEqual(valid_ref(ref), actual.returncode == 0, ref)


if __name__ == '__main__':
    unittest.main()

"""Exercise actual Git commits and staged blobs in disposable repositories."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / 'checkout with spaces'
    path.mkdir()
    for name in ('.githooks/pre-commit', 'scripts/check-file-size.py', 'scripts/install-hooks.py'):
        target = path / name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(ROOT / name, target)
    env = {**os.environ, 'TERM_AGENT_HOOK_PYTHON': sys.executable,
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
           'GIT_AUTHOR_NAME': 'Hook Test', 'GIT_AUTHOR_EMAIL': 'hook@example.invalid',
           'GIT_COMMITTER_NAME': 'Hook Test', 'GIT_COMMITTER_EMAIL': 'hook@example.invalid'}

    def run(*args):
        return subprocess.run(args, cwd=path, env=env, capture_output=True, text=True, encoding='utf-8')

    assert run('git', 'init', '-q').returncode == 0
    assert run(sys.executable, 'scripts/install-hooks.py').returncode == 0
    assert run('git', 'config', '--get', 'core.hooksPath').stdout.strip() == '.githooks'
    assert run('git', 'add', '.').returncode == 0
    assert run('git', 'commit', '-qm', 'Install guard').returncode == 0
    return path, run


def test_oversized_staged_commit_rejected_then_split_commit_succeeds(repo):
    path, run = repo
    source = path / 'oversized.py'
    source.write_bytes(b'#' * 20_001)
    assert run('git', 'add', 'oversized.py').returncode == 0
    source.write_text('# Unstaged edit must not bypass the guard.\n')
    result = run('git', 'commit', '-qm', 'Must fail')
    assert result.returncode != 0
    assert '20,001 staged bytes' in result.stderr and 'Split source by responsibility' in result.stderr
    assert run('git', 'log', '--format=%s').stdout.splitlines() == ['Install guard']
    source.write_bytes(b'#' * 12_000)
    (path / 'second.py').write_bytes(b'#' * 8_001)
    assert run('git', 'add', 'oversized.py', 'second.py').returncode == 0
    result = run('git', 'commit', '-qm', 'Split source')
    assert result.returncode == 0, result.stderr
    assert run('git', 'log', '-1', '--format=%s').stdout.strip() == 'Split source'


def test_small_staged_blob_allowed_despite_large_working_file(repo):
    path, run = repo
    source = path / 'small.py'
    source.write_bytes(b'#' * 20_000)
    assert run('git', 'add', 'small.py').returncode == 0
    source.write_bytes(b'#' * 25_000)
    result = run('git', 'commit', '-qm', 'Exact limit')
    assert result.returncode == 0, result.stderr
    assert run('git', 'cat-file', '-s', 'HEAD:small.py').stdout.strip() == '20000'


@pytest.mark.parametrize('name', ['Unicode 名称.py', 'line\nbreak.py'])
def test_renamed_oversized_source_is_checked(repo, name):
    if '\n' in name and os.name == 'nt':
        pytest.skip('Windows file names cannot contain newlines.')
    path, run = repo
    lockfile = path / 'requirements-lock.txt'
    lockfile.write_bytes(b'#' * 20_001)
    assert run('git', 'add', 'requirements-lock.txt').returncode == 0
    assert run('git', 'commit', '-qm', 'Exempt lock').returncode == 0
    assert run('git', 'mv', 'requirements-lock.txt', name).returncode == 0
    result = run('git', 'commit', '-qm', 'Must inspect rename')
    assert result.returncode != 0 and '20,001 staged bytes' in result.stderr


def test_known_generated_files_and_deletions_are_allowed(repo):
    path, run = repo
    for name in ('pnpm-lock.yaml', 'build/generated.js', 'vendor.min.js'):
        target = path / name
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'#' * 25_000)
        assert run('git', 'add', name).returncode == 0
    assert run('git', 'commit', '-qm', 'Generated files').returncode == 0
    assert run('git', 'rm', 'pnpm-lock.yaml').returncode == 0
    result = run('git', 'commit', '-qm', 'Delete file')
    assert result.returncode == 0, result.stderr


def test_installer_preserves_other_hook_configuration(repo):
    _, run = repo
    assert run('git', 'config', '--local', 'core.hooksPath', 'other-hooks').returncode == 0
    result = run(sys.executable, 'scripts/install-hooks.py')
    assert result.returncode != 0 and 'retained' in result.stderr
    assert run('git', 'config', '--get', 'core.hooksPath').stdout.strip() == 'other-hooks'


def test_installer_preserves_unconfigured_legacy_hooks(repo):
    path, run = repo
    assert run('git', 'config', '--local', '--unset', 'core.hooksPath').returncode == 0
    hook = path / '.git/hooks/pre-commit'
    hook.write_text('#!/bin/sh\nexit 0\n')
    result = run(sys.executable, 'scripts/install-hooks.py')
    assert result.returncode != 0 and 'retained' in result.stderr
    assert hook.read_text() == '#!/bin/sh\nexit 0\n'
    assert run('git', 'config', '--get', 'core.hooksPath').returncode == 1

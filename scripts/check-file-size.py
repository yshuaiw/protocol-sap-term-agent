"""Reject oversized staged source blobs, without inspecting unstaged contents."""
from pathlib import PurePosixPath
import subprocess
import sys

LIMIT = 20_000
LOCKFILES = {
    'package-lock.json', 'npm-shrinkwrap.json', 'pnpm-lock.yaml', 'yarn.lock',
    'poetry.lock', 'uv.lock', 'Pipfile.lock', 'Cargo.lock', 'requirements-lock.txt',
}
GENERATED_DIRS = {'node_modules', 'dist', 'build', '__pycache__', '.venv'}
GENERATED_SUFFIXES = ('.min.js', '.min.css', '.map', '.generated.py', '.generated.js', '.generated.ts')


def exempt(name):
    path = PurePosixPath(name)
    return (path.name in LOCKFILES or bool(set(path.parts[:-1]) & GENERATED_DIRS)
            or name.endswith(GENERATED_SUFFIXES))


def git(*args):
    return subprocess.check_output(['git', *args])


def main():
    names = git('diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z').split(b'\0')
    oversized = []
    for raw in filter(None, names):
        name = raw.decode('utf-8', errors='surrogateescape')
        if not exempt(name):
            size = int(git('cat-file', '-s', ':' + name))
            if size > LIMIT:
                oversized.append((name, size))
    for name, size in oversized:
        print(f'File size limit: {ascii(name)} has {size:,} staged bytes '
              f'(~{size / 4:,.0f} tokens); limit is {LIMIT:,} bytes.', file=sys.stderr)
    if oversized:
        print('Split source by responsibility, stage the smaller files, and retry the commit.', file=sys.stderr)
    return bool(oversized)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'Could not inspect staged files ({type(exc).__name__}); commit stopped.', file=sys.stderr)
        sys.exit(1)

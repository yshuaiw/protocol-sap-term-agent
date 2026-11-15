"""Install this checkout's versioned hooks without replacing unrelated hooks."""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if not (ROOT / '.git').exists():
        print('No Git checkout; skipping development hooks.')
        return 0
    if not shutil.which('git'):
        print('Git is required to install development hooks.', file=sys.stderr)
        return 1
    configured = subprocess.run(['git', 'config', '--get', 'core.hooksPath'], cwd=ROOT,
                                capture_output=True, text=True)
    if configured.returncode not in (0, 1):
        raise RuntimeError('Could not read Git hook configuration.')
    current = configured.stdout.strip()
    if current and current != '.githooks':
        print('Existing core.hooksPath retained; integrate scripts/check-file-size.py '
              'into your current pre-commit hook before committing.', file=sys.stderr)
        return 1
    if not current:
        hook_dir = subprocess.check_output(['git', 'rev-parse', '--git-path', 'hooks'], cwd=ROOT, text=True).strip()
        path = Path(hook_dir)
        if not path.is_absolute():
            path = ROOT / path
        if any(p.is_file() and not p.name.endswith('.sample') for p in path.glob('*')):
            print('Existing local hooks retained; integrate the size check before switching hooksPath.', file=sys.stderr)
            return 1
    hook = ROOT / '.githooks/pre-commit'
    hook.chmod(hook.stat().st_mode | 0o111)
    subprocess.run(['git', 'config', '--local', 'core.hooksPath', '.githooks'], cwd=ROOT, check=True)
    print('Installed local pre-commit hook: .githooks/pre-commit (20,000 staged bytes).')
    return 0


if __name__ == '__main__':
    sys.exit(main())

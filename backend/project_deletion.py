"""Checked removal of one project's internal files, never external copies/settings."""
import os
import shutil

from .project_lifecycle import ProjectMissing, ProjectStateError


def checked_folder(store, pid):
    root = store.root.resolve(strict=True)
    folder = store.folder(pid)
    if folder.is_symlink() or folder.is_junction():
        raise ValueError('Cannot delete a linked project directory.')
    try:
        target = folder.resolve(strict=True)
    except FileNotFoundError:
        raise ProjectMissing('Project no longer exists. Reload the project list.') from None
    if target.parent != root or target.name != pid or not target.is_dir():
        raise ValueError('Project deletion target must be an immediate directory inside the project store.')
    return target


def summary(store, pid):
    from .store import LOCK
    if store.activity.busy(pid):
        raise ProjectStateError('This project has an active operation. Wait for it to finish before deleting.')
    with LOCK:
        folder = checked_folder(store, pid)
        project = store.load(pid)  # Deliberately independent of source-file validity.
        return {'id': pid, 'name': project['name'], 'revision': project['revision'],
                'first_saved': next((h['time'] for h in project.get('history', []) if h.get('time')), None),
                'updated': project['updated'],
                'documents': [{'role': d['role'], 'name': d['name']} for d in project['documents']],
                'concepts': len(project['concepts']), 'occurrences': len(project['mentions']),
                'snapshots': sum(1 for p in (folder / 'snapshots').glob('*.json') if p.is_file()),
                'exports': len(project['exports'])}


def check_contents(folder):
    # Refuse linked descendants before removing anything. This also protects Windows
    # junctions and keeps deletion within the absolute target verified above.
    for current, directories, files in os.walk(folder, followlinks=False):
        for name in directories + files:
            item = folder / os.path.relpath(os.path.join(current, name), folder)
            if item.is_symlink() or item.is_junction() or not item.resolve().is_relative_to(folder):
                raise ValueError('Project contains linked paths. Remove those links before deleting the project.')


def delete(store, pid, revision):
    from .store import LOCK
    with store.activity.deletion(pid), LOCK:
        folder = checked_folder(store, pid)
        project = store.load(pid)
        if project['revision'] != revision:
            raise ProjectStateError('Project changed after the deletion preview. Refresh its details and confirm again.')
        check_contents(folder)
        manifest = folder / 'project.json'
        original = manifest.read_bytes()
        try:
            # Keep the current manifest until all other data is removed. A locked file
            # must leave this project visible and deletable even when sources are gone.
            for path in folder.iterdir():
                if path == manifest:
                    continue
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            manifest.unlink()
            try:
                folder.rmdir()
            except OSError:
                manifest.write_bytes(original)
                raise
        except OSError:
            raise ProjectStateError('Deletion did not finish. Some internal files may already be removed. Close files using this project and retry.') from None
        return {'id': pid, 'deleted': True}

"""Atomic versioned project files with a portable, bounded archive format."""
import copy
import io
import json
import os
import re
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

LOCK = threading.RLock()
MAX_BUNDLE = 200 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, pid):
        if not re.fullmatch(r'[0-9a-f]{32}', pid):
            raise ValueError('Invalid project ID.')
        return self.root / pid

    def load(self, pid):
        try:
            return json.loads((self.folder(pid) / 'project.json').read_text(encoding='utf-8'))
        except FileNotFoundError:
            raise ValueError('Project not found.')

    def list(self):
        return sorted([{'id': p['id'], 'name': p['name'], 'revision': p['revision'], 'updated': p['updated']}
                       for f in self.root.glob('*/project.json') for p in [json.loads(f.read_text(encoding='utf-8'))]],
                      key=lambda p: p['updated'], reverse=True)

    def create(self, name, documents, inputs, version_note):
        pid = uuid.uuid4().hex
        folder = self.folder(pid)
        (folder / 'inputs').mkdir(parents=True)
        for filename, content in inputs.items():
            (folder / 'inputs' / filename).write_bytes(content)
        project = {'schema': 1, 'id': pid, 'name': name, 'revision': 0, 'documents': documents,
                   'concepts': [], 'mentions': [], 'plans': [], 'exports': [], 'history': [],
                   'version_note': version_note, 'engine': 'pending', 'ai_runs': [], 'semantic_audits': []}
        return self.save(project, 'Imported immutable original documents and indexed selected regions; AI generation not yet run')

    def save(self, project, action):
        folder = self.folder(project['id'])
        (folder / 'snapshots').mkdir(parents=True, exist_ok=True)
        project['revision'] += 1
        project['updated'] = now()
        project['history'].append({'revision': project['revision'], 'time': project['updated'], 'action': action})
        payload = json.dumps(project, ensure_ascii=False, indent=2)
        snapshot = folder / 'snapshots' / f"{project['revision']:06d}.json"
        snapshot.write_text(payload, encoding='utf-8')
        temp = folder / 'project.tmp'
        temp.write_text(payload, encoding='utf-8')
        os.replace(temp, folder / 'project.json')
        return project

    def restore(self, pid, revision):
        current = self.load(pid)
        if not 1 <= revision <= current['revision']:
            raise ValueError('Unknown history revision.')
        restored = json.loads((self.folder(pid) / 'snapshots' / f'{revision:06d}.json').read_text(encoding='utf-8'))
        restored['revision'], restored['history'] = current['revision'], current['history']
        restored['plans'] = []
        return self.save(restored, f'Restored snapshot {revision} as a new revision')

    def bundle(self, pid):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
            for f in self.folder(pid).rglob('*'):
                relative = f.relative_to(self.folder(pid)).as_posix()
                if f.is_file() and (relative == 'project.json' or relative.startswith(('inputs/', 'snapshots/', 'exports/'))):
                    archive.write(f, f.relative_to(self.folder(pid)).as_posix())
        return data.getvalue()

    def import_bundle(self, content):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 3000 or sum(i.file_size for i in entries) > MAX_BUNDLE:
                raise ValueError('Project bundle exceeds size limits.')
            names = [i.filename for i in entries]
            if len(set(names)) != len(names):
                raise ValueError('Duplicate archive entries.')
            pattern = r'(project\.json|inputs/[0-9a-f]{16}\.(pdf|docx)|snapshots/\d{6}\.json|exports/[0-9a-f]{32}/[A-Za-z0-9_.-]+)'
            if any(not re.fullmatch(pattern, name) for name in names):
                raise ValueError('Unsafe or unexpected archive path.')
            project = json.loads(archive.read('project.json'))
            if project.get('schema') != 1 or {d['role'] for d in project['documents']} != {'Protocol', 'SAP'}:
                raise ValueError('Unsupported project schema or missing document pair.')
            # Validate every restorable state before writing any imported files.
            import hashlib
            states = [project] + [json.loads(archive.read(n)) for n in names if n.startswith('snapshots/')]
            for state in states:
                if state.get('schema') != 1 or not isinstance(state.get('revision'), int) or state['revision'] < 1:
                    raise ValueError('Invalid project snapshot.')
                if not isinstance(state.get('name'), str) or not 1 <= len(state['name']) <= 200:
                    raise ValueError('Project snapshot needs a valid name.')
                if not isinstance(state.get('version_note'), str) or not isinstance(state.get('updated'), str):
                    raise ValueError('Project snapshot is missing provenance fields.')
                for field in ('documents', 'concepts', 'mentions', 'plans', 'exports', 'history'):
                    if not isinstance(state.get(field), list):
                        raise ValueError('Invalid project snapshot fields.')
                for doc in state['documents']:
                    source = doc['source']
                    if not re.fullmatch(r'[0-9a-f]{16}\.(pdf|docx)', source) or f'inputs/{source}' not in names:
                        raise ValueError('Missing or unsafe original PDF in project bundle.')
                    if hashlib.sha256(archive.read(f'inputs/{source}')).hexdigest() != doc['sha256']:
                        raise ValueError('Original PDF hash mismatch in bundle.')
                for result in state['exports']:
                    if not re.fullmatch(r'[0-9a-f]{32}', result['id']) or any(
                        not re.fullmatch(r'[A-Za-z0-9_.-]+', f) or f'exports/{result["id"]}/{f}' not in names
                        for f in result['files']):
                        raise ValueError('Missing or unsafe export in project bundle.')
            # Imported projects get a new identity, preserving all snapshots and audit actions.
            old_id = project['id']
            pid = uuid.uuid4().hex
            folder = self.folder(pid)
            for item in entries:
                target = folder / item.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                raw = archive.read(item)
                if item.filename == 'project.json' or item.filename.startswith('snapshots/'):
                    state = json.loads(raw)
                    state['id'] = pid
                    raw = json.dumps(state, ensure_ascii=False).encode('utf-8')
                target.write_bytes(raw)
            project['id'] = pid
            self.validate_sources(project)
            return self.save(project, f'Imported portable project from {old_id}')

    def validate_sources(self, project):
        import hashlib
        for doc in project['documents']:
            source = doc['source']
            if not re.fullmatch(r'[0-9a-f]{16}\.(pdf|docx)', source):
                raise ValueError('Invalid source filename.')
            path = self.folder(project['id']) / 'inputs' / source
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != doc['sha256']:
                raise ValueError('Original PDF hash mismatch.')

    @staticmethod
    def clone(project):
        return copy.deepcopy(project)

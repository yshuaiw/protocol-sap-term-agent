"""Accepted results survive operational budget changes; semantic inputs still match exactly."""
import hashlib
import json

CONTROL_FIELDS = {'max_calls', 'max_output_tokens', 'text_rpm', 'vision_rpm'}


def semantic_config(config):
    return {k: v for k, v in config.items() if k not in CONTROL_FIELDS}


def cache_digest(parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


class CacheIdentity:
    def __init__(self, folder):
        self.folder = folder
        self.history = None

    def paths(self, parts):
        canonical = list(parts)
        canonical[3] = semantic_config(parts[3])
        digest = cache_digest(['accepted-cache-v2', *canonical])
        primary = self.folder / (digest + '.json') if self.folder else None
        if not primary:
            return digest, []
        # Legacy filenames included runtime budgets. Reconstruct only exact compatible identities.
        if self.history is None:
            self.history = []
            try:
                project = json.loads((self.folder.parent / 'project.json').read_text(encoding='utf-8'))
                for run in project.get('ai_runs', []):
                    self.history.append(run.get('configuration', {}))
                    self.history.extend(c.get('configuration', {}) for c in run.get('calls', []))
            except (OSError, ValueError, TypeError, AttributeError):
                pass  # Optional legacy lookup cannot replace validation of a cache result.
        configurations = {json.dumps(parts[3], sort_keys=True): parts[3]}
        for config in self.history:
            if isinstance(config, dict) and semantic_config(config) == canonical[3]:
                configurations[json.dumps(config, sort_keys=True)] = config
        paths = [primary]
        for config in configurations.values():
            legacy = list(parts)
            legacy[3] = config
            paths.append(self.folder / (cache_digest(legacy) + '.json'))
        return digest, paths

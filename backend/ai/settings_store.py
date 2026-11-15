"""Private machine configuration, deliberately outside the project store/bundles."""
import json
import os
import re
import threading
from pathlib import Path

from .providers import PROVIDERS

SETTINGS_FILE = '.env.providers.json'  # Existing .env.* ignore rule applies.
CONFIG_LOCK = threading.RLock()


def read_local(root):
    path = Path(root) / SETTINGS_FILE
    if not path.exists():
        return {'credentials': {}, 'selection': {}}
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value['credentials'], dict) or not isinstance(value['selection'], dict):
            raise ValueError()
        return value
    except (ValueError, KeyError, TypeError):
        raise ValueError('Local API settings are invalid. Repair the local configuration file; contents withheld.') from None


def valid_model(model):
    return isinstance(model, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,149}', model) and '..' not in model


def update_local(root, selection=None, credential=None):
    """Null credential disables legacy fallback without modifying API.txt or the environment."""
    with CONFIG_LOCK:
        value = read_local(root)
        if selection is not None:
            expected = {'provider', 'model', 'vision_provider', 'vision_model', 'pdf_mode'}
            if set(selection) != expected or any(selection[p] not in PROVIDERS for p in ('provider', 'vision_provider')):
                raise ValueError('Select a supported text and visual provider.')
            if not all(valid_model(selection[p]) for p in ('model', 'vision_model')):
                raise ValueError('Enter valid model IDs for both tasks.')
            if selection['pdf_mode'] not in ('text', 'vision', 'native'):
                raise ValueError('Select text, vision or native PDF processing.')
            visual = PROVIDERS[selection['vision_provider']]
            if selection['pdf_mode'] == 'native' and not visual['native_pdf']:
                raise ValueError('This visual adapter does not support native PDF. Select a supported provider or another processing mode.')
            if selection['pdf_mode'] != 'text' and not visual['vision']:
                raise ValueError('This adapter supports text tasks only.')
            value['selection'] = selection
        if credential is not None:
            provider, key = credential
            if provider not in PROVIDERS:
                raise ValueError('Unknown provider.')
            if key is not None and (not isinstance(key, str) or not 8 <= len(key) <= 512 or
                                    not key.isascii() or any(c.isspace() or ord(c) < 33 for c in key)):
                raise ValueError('Invalid key format; key contents withheld.')
            value['credentials'][provider] = key
        secrets = [k for k in value['credentials'].values() if isinstance(k, str) and k]
        if any(k in str(value['selection']) for k in secrets):
            raise ValueError('Credentials cannot be used as model IDs.')
        path = Path(root) / SETTINGS_FILE
        temp = path.with_suffix('.json.tmp')
        try:
            with temp.open('w', encoding='utf-8') as handle:
                json.dump(value, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        except OSError:
            raise ValueError('Could not save local API settings. Check workspace write access; contents withheld.') from None

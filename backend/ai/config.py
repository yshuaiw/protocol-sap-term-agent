import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def local_options(root=ROOT):
    options = {}
    path = root / '.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                options[key.strip()] = value.strip().strip('"\'')
    return {**options, **os.environ}


def read_key(options, root):
    if options.get('GROQ_API_KEY', '').strip():
        return options['GROQ_API_KEY'].strip()
    path = root / 'API.txt'
    if not path.is_file():
        return ''
    raw = path.read_text(encoding='utf-8-sig').strip()
    if raw.startswith('{'):
        try:
            value = json.loads(raw)
            raw = value.get('GROQ_API_KEY', value.get('groq_api_key', ''))
        except (ValueError, AttributeError):
            return ''
    elif raw.startswith('GROQ_API_KEY='):
        raw = raw.split('=', 1)[1].strip().strip('"\'')
    return raw if isinstance(raw, str) and len(raw) <= 512 and not any(c.isspace() for c in raw) else ''


@dataclass
class Settings:
    api_key: str = field(default='', repr=False)
    model: str = 'openai/gpt-oss-20b'
    vision_model: str = 'qwen/qwen3.8-27b'
    pdf_mode: str = 'vision'
    offline: bool = False
    max_calls: int = 500
    chunk_chars: int = 7000
    chunk_units: int = 8
    link_batch_size: int = 8
    max_output_tokens: int = 4096

    @classmethod
    def load(cls, root=ROOT):
        env = local_options(root)
        mode = env.get('TERM_AGENT_PDF_MODE', 'vision')
        if mode not in ('vision', 'text'):
            raise ValueError('TERM_AGENT_PDF_MODE must be vision or text.')
        return cls(api_key=read_key(env, root), model=env.get('GROQ_MODEL', cls.model),
                   vision_model=env.get('GROQ_VISION_MODEL', cls.vision_model), pdf_mode=mode,
                   offline=env.get('TERM_AGENT_OFFLINE', '0') == '1',
                   max_calls=max(1, min(1000, int(env.get('TERM_AGENT_MAX_CALLS', '500')))),
                   chunk_chars=max(1000, min(15000, int(env.get('TERM_AGENT_CHUNK_CHARS', '7000')))),
                   chunk_units=max(1, min(32, int(env.get('TERM_AGENT_CHUNK_UNITS', '8')))),
                   link_batch_size=max(1, min(20, int(env.get('TERM_AGENT_LINK_BATCH_SIZE', '8')))),
                   max_output_tokens=max(512, min(16384, int(env.get('TERM_AGENT_MAX_OUTPUT_TOKENS', '4096')))))

    def public(self):
        return {'provider': 'groq', 'key_configured': bool(self.api_key), 'model': self.model,
                'vision_model': self.vision_model, 'pdf_mode': self.pdf_mode, 'offline': self.offline,
                'native_pdf': False, 'image_input': bool(self.vision_model), 'max_calls': self.max_calls,
                'chunk_chars': self.chunk_chars, 'chunk_units': self.chunk_units, 'max_output_tokens': self.max_output_tokens,
                'link_batch_size': self.link_batch_size,
                'notice': 'Configuration does not verify credentials, quota, model access or document quality. Keys are backend-only.'}

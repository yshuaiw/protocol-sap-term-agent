import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from .providers import PROVIDERS, ADAPTER_VERSION
from .settings_store import CONFIG_LOCK, read_local, valid_model
from .rate_policy import DEFAULT_RPM, validate_profiles
from .run_policy import DEFAULT_RUN_LIMITS, RUN_LIMIT_RANGES, validate_limits

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


def credentials(env, local, root):
    keys, status = {}, {}
    for pid, info in PROVIDERS.items():
        managed = pid in local['credentials']
        key = local['credentials'].get(pid) if managed else (read_key(env, root) if pid == 'groq' else
              env.get(info['key_env'], env.get('GEMINI_API_KEY', '') if pid == 'google' else ''))
        if key is not None and not isinstance(key, str):
            raise ValueError('Invalid local credential configuration; contents withheld.')
        keys[pid] = key or ''
        status[pid] = {'key_configured': bool(key), 'key_source': 'saved locally' if managed and key else
                      'disabled locally' if managed else 'legacy file/environment' if key else 'not configured'}
    return keys, status


def number(env, key, default, low, high):
    try:
        return max(low, min(high, int(env.get(key, str(default)))))
    except (ValueError, TypeError):
        raise ValueError('Invalid numeric API setting; configuration contents withheld.') from None


@dataclass
class Settings:
    api_key: str = field(default='', repr=False)
    model: str = 'openai/gpt-oss-20b'
    vision_model: str = 'qwen/qwen3.8-27b'
    provider: str = 'groq'
    vision_provider: str = 'groq'
    vision_api_key: str | None = field(default=None, repr=False)
    key_status: dict = field(default_factory=dict, repr=False)
    pdf_mode: str = 'vision'
    offline: bool = False
    max_calls: int = DEFAULT_RUN_LIMITS['max_calls']
    chunk_chars: int = 7000
    chunk_units: int = 8
    link_batch_size: int = 8
    max_output_tokens: int = DEFAULT_RUN_LIMITS['max_output_tokens']
    rate_limits: dict = field(default_factory=dict)

    @classmethod
    def load(cls, root=ROOT):
        env = local_options(root)
        with CONFIG_LOCK:
            local = read_local(root)
        selected = local['selection']
        provider, visual = selected.get('provider', 'groq'), selected.get('vision_provider', 'groq')
        if provider not in PROVIDERS or visual not in PROVIDERS:
            raise ValueError('Unsupported provider in local API settings.')
        keys, status = credentials(env, local, root)
        rates = validate_profiles(local.get('rate_limits', {}))
        limits = validate_limits(local['run_limits']) if 'run_limits' in local else validate_limits({
            key: number(env, 'TERM_AGENT_' + key.upper(), default, *RUN_LIMIT_RANGES[key])
            for key, default in DEFAULT_RUN_LIMITS.items()})
        if any(k and k in str(rates) for k in keys.values()):
            raise ValueError('Invalid local RPM settings; contents withheld.')
        mode = selected.get('pdf_mode', env.get('TERM_AGENT_PDF_MODE', 'vision'))
        if mode not in ('vision', 'text', 'native'):
            raise ValueError('TERM_AGENT_PDF_MODE must be vision, text or native.')
        model = selected.get('model', env.get('GROQ_MODEL', cls.model))
        vision_model = selected.get('vision_model', env.get('GROQ_VISION_MODEL', cls.vision_model))
        if not valid_model(model) or not valid_model(vision_model) or any(k and k in model + vision_model for k in keys.values()):
            raise ValueError('Invalid model ID; configuration contents withheld.')
        return cls(api_key=keys[provider], model=model, provider=provider, vision_provider=visual,
                   vision_api_key=keys[visual], key_status=status, vision_model=vision_model, pdf_mode=mode, rate_limits=rates,
                   offline=env.get('TERM_AGENT_OFFLINE', '0') == '1',
                   max_calls=limits['max_calls'],
                   chunk_chars=number(env, 'TERM_AGENT_CHUNK_CHARS', 7000, 1000, 15000),
                   chunk_units=number(env, 'TERM_AGENT_CHUNK_UNITS', 8, 1, 32),
                   link_batch_size=number(env, 'TERM_AGENT_LINK_BATCH_SIZE', 8, 1, 20),
                   max_output_tokens=limits['max_output_tokens'])

    def public(self):
        return {'provider': self.provider, 'vision_provider': self.vision_provider,
                'rate_limits': self.rate_limits, 'rate_defaults': DEFAULT_RPM,
                'text_rpm': self.request_rpm(self.provider, self.model),
                'vision_rpm': self.request_rpm(self.vision_provider, self.vision_model),
                'key_configured': bool(self.api_key), 'vision_key_configured': bool(self.visual_key()), 'model': self.model,
                'vision_model': self.vision_model, 'pdf_mode': self.pdf_mode, 'offline': self.offline,
                'native_pdf': PROVIDERS[self.vision_provider]['native_pdf'],
                'image_input': bool(PROVIDERS[self.vision_provider]['vision']), 'max_calls': self.max_calls,
                'chunk_chars': self.chunk_chars, 'chunk_units': self.chunk_units, 'max_output_tokens': self.max_output_tokens,
                'link_batch_size': self.link_batch_size, 'run_limit_defaults': DEFAULT_RUN_LIMITS,
                'run_limit_ranges': RUN_LIMIT_RANGES,
                'providers': {pid: {'name': info['name'], 'model': info['model'], 'vision_model': info['vision'],
                                   'native_pdf': info['native_pdf'], 'image_input': bool(info['vision']),
                                   **self.key_status.get(pid, {'key_configured': False, 'key_source': 'not configured'})}
                              for pid, info in PROVIDERS.items()},
                'notice': 'Saved settings apply to the next operation. No automatic provider fallback. Model IDs are editable examples; access is unverified. Keys stay on this machine.'}

    def visual_key(self):
        return self.vision_api_key if self.vision_api_key is not None else (self.api_key if self.provider == self.vision_provider else '')

    def request_rpm(self, provider, model):
        return self.rate_limits.get(provider, {}).get(model, DEFAULT_RPM[provider])

    def provenance(self):
        """Allowlist only non-secret request-affecting settings for portable history."""
        return {key: getattr(self, key) for key in ('provider', 'model', 'vision_provider', 'vision_model', 'pdf_mode',
                'max_calls', 'chunk_chars', 'chunk_units', 'link_batch_size', 'max_output_tokens')} | {
                    'adapter': ADAPTER_VERSION, 'text_rpm': self.request_rpm(self.provider, self.model),
                    'vision_rpm': self.request_rpm(self.vision_provider, self.vision_model)}

"""Application starting caps, not statements about provider/account quotas."""
from .providers import PROVIDERS

DEFAULT_RPM = {provider: 10 for provider in PROVIDERS} | {'groq': 20, 'google': 4}


def valid_rpm(value):
    return type(value) is int and 1 <= value <= 1000


def validate_profiles(value):
    from .settings_store import valid_model
    if not isinstance(value, dict) or any(p not in PROVIDERS for p in value):
        raise ValueError('Invalid local RPM settings; contents withheld.')
    for profiles in value.values():
        if not isinstance(profiles, dict) or len(profiles) > 64 or any(
                not valid_model(m) or not valid_rpm(rpm) for m, rpm in profiles.items()):
            raise ValueError('RPM must be an integer from 1 to 1000 for a valid provider/model; contents withheld.')
    return value

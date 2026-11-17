"""Application budgets, not claims about a provider model's supported limits."""
DEFAULT_RUN_LIMITS = {'max_calls': 10000, 'max_output_tokens': 16384}
RUN_LIMIT_RANGES = {'max_calls': (1, 1000000), 'max_output_tokens': (512, 131072)}


def validate_limits(value):
    if (not isinstance(value, dict) or set(value) != set(DEFAULT_RUN_LIMITS) or
            any(type(value[k]) is not int or not low <= value[k] <= high
                for k, (low, high) in RUN_LIMIT_RANGES.items())):
        raise ValueError('Run limits require integer HTTP attempts from 1 to 1000000 and output tokens from 512 to 131072; contents withheld.')
    return dict(value)

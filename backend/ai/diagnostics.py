"""Structural rejection summaries only: never retain generated/source text."""
import json
from collections import Counter

from pydantic import ValidationError


def rejected_output_summary(error, schema):
    raw = error.get('failed_generation') if isinstance(error, dict) else None
    if not isinstance(raw, str) or not raw:
        return {'output_available': False}
    summary = {'output_available': True, 'characters': len(raw)}
    # Do not parse unbounded untrusted provider data or copy it to logs/errors.
    if len(raw) > 200000:
        return {**summary, 'analysis_limit_exceeded': True}
    summary.update(markdown_fence=raw.lstrip().startswith('```'),
                   reasoning_marker='<think>' in raw or '<|channel|>analysis' in raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {**summary, 'valid_json': False, 'line': exc.lineno, 'column': exc.colno,
                'possibly_incomplete': not raw.rstrip().endswith(('}', ']'))}
    except (ValueError, RecursionError):
        return {**summary, 'valid_json': False, 'analysis_limit_exceeded': True}
    summary['valid_json'] = True
    try:
        schema.model_validate(data)
    except ValidationError as exc:
        # Type labels come from Pydantic, never include input, context or field names.
        counts = Counter(item['type'] for item in exc.errors(include_input=False, include_context=False))
        summary.update(schema_valid=False, validation_errors=dict(counts))
    except (ValueError, RecursionError):
        summary.update(schema_valid=False, analysis_limit_exceeded=True)
    else:
        summary['schema_valid'] = True
    return summary

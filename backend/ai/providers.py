"""Fixed first-party endpoints and provider wire formats. No network at import time."""
from .response_errors import OutputError
import copy

PROVIDERS = {
    'groq': dict(name='Groq', base='https://api.groq.com/openai/v1', key_env='GROQ_API_KEY',
                 model='openai/gpt-oss-20b', vision='qwen/qwen3.8-27b', native_pdf=False),
    'google': dict(name='Google', base='https://generativelanguage.googleapis.com/v1beta', key_env='GOOGLE_API_KEY',
                   model='gemini-2.5-flash', vision='gemini-2.5-flash', native_pdf=True),
    'openai': dict(name='OpenAI', base='https://api.openai.com/v1', key_env='OPENAI_API_KEY',
                   model='gpt-4.1-mini', vision='gpt-4.1-mini', native_pdf=True),
    'anthropic': dict(name='Anthropic', base='https://api.anthropic.com/v1', key_env='ANTHROPIC_API_KEY',
                      model='claude-sonnet-4-5', vision='claude-sonnet-4-5', native_pdf=True),
    'deepseek': dict(name='DeepSeek', base='https://api.deepseek.com', key_env='DEEPSEEK_API_KEY',
                     model='deepseek-chat', vision='', native_pdf=False),
    'qwen': dict(name='Qwen (Singapore)', base='https://dashscope-intl.aliyuncs.com/compatible-mode/v1',
                 key_env='DASHSCOPE_API_KEY', model='qwen-plus', vision='qwen-vl-plus', native_pdf=False),
    'kimi': dict(name='Kimi (international)', base='https://api.moonshot.ai/v1', key_env='MOONSHOT_API_KEY',
                 model='kimi-k2.5', vision='kimi-k2.5', native_pdf=False),
}
STRICT_MODELS = {'openai/gpt-oss-20b', 'openai/gpt-oss-120b', 'qwen/qwen3.8-27b', 'meta-models/muse-spark-open'}
ADAPTER_VERSION = 'providers-v1'


def wire_schema(schema):
    """Provider subset; original constraints remain mandatory in local validation."""
    value = copy.deepcopy(schema)
    def clean(node):
        if isinstance(node, dict):
            for key in ('minLength', 'maxLength', 'minItems', 'maxItems', 'minimum', 'maximum', 'title', 'default'):
                node.pop(key, None)
            for child in node.values():
                clean(child)
        elif isinstance(node, list):
            for child in node:
                clean(child)
    clean(value)
    return value


def request_spec(provider, model, key, stage, prompt, text, schema, tokens, images=None, pdf=None):
    """Return path, headers, body and response-format label. Keys only in headers."""
    images = images or []
    if provider == 'google':
        parts = [{'text': text}]
        for url in images + ([pdf] if pdf else []):
            media, data = url.split(';base64,', 1)
            parts.append({'inlineData': {'mimeType': media[5:], 'data': data}})
        body = {'systemInstruction': {'parts': [{'text': prompt}]},
                'contents': [{'role': 'user', 'parts': parts}],
                'generationConfig': {'maxOutputTokens': tokens, 'responseMimeType': 'application/json',
                                     'responseJsonSchema': wire_schema(schema)}}
        return f'/models/{model}:generateContent', {'x-goog-api-key': key}, body, 'json_schema'
    if provider == 'anthropic':
        content = [{'type': 'text', 'text': text}]
        for url in images + ([pdf] if pdf else []):
            media, data = url.split(';base64,', 1)
            content.append({'type': 'document' if media[5:] == 'application/pdf' else 'image',
                            'source': {'type': 'base64', 'media_type': media[5:], 'data': data}})
        body = {'model': model, 'system': prompt, 'messages': [{'role': 'user', 'content': content}],
                'max_tokens': tokens, 'output_config': {'format': {'type': 'json_schema', 'schema': wire_schema(schema)}}}
        return '/messages', {'x-api-key': key, 'anthropic-version': '2023-06-01'}, body, 'json_schema'
    content = [{'type': 'text', 'text': text}]
    content.extend({'type': 'image_url', 'image_url': {'url': url}} for url in images)
    if pdf:
        content.append({'type': 'file', 'file': {'filename': 'source.pdf', 'file_data': pdf}})
    strict = provider == 'groq' and model in STRICT_MODELS and not images
    response_format = {'type': 'json_schema', 'json_schema': {
        'name': stage, 'strict': True, 'schema': schema}} if strict else {'type': 'json_object'}
    body = {'model': model, 'messages': [{'role': 'system', 'content': prompt},
            {'role': 'user', 'content': content if images or pdf else text}], 'response_format': response_format,
            'max_completion_tokens' if provider in ('groq', 'openai') else 'max_tokens': tokens}
    if provider == 'groq' and stage in ('discovery', 'discovery_repair', 'boundary_scan', 'boundary_review') and model in ('openai/gpt-oss-20b', 'openai/gpt-oss-120b'):
        body['reasoning_effort'] = 'medium' if stage == 'boundary_review' else 'low'
    if provider in ('qwen', 'kimi'):
        body['enable_thinking' if provider == 'qwen' else 'thinking'] = False if provider == 'qwen' else {'type': 'disabled'}
    return '/chat/completions', {'Authorization': 'Bearer ' + key}, body, response_format['type']


def response_content(provider, data):
    """Normalize only complete, non-refused responses. Caller validates original schema."""
    if provider == 'google':
        if data.get('promptFeedback', {}).get('blockReason'):
            raise OutputError('was refused by the provider')
        candidate = data['candidates'][0]
        if candidate.get('finishReason') == 'MAX_TOKENS':
            raise OutputError('was truncated at the output token limit')
        if candidate['finishReason'] != 'STOP' or data.get('promptFeedback', {}).get('blockReason'):
            raise OutputError('was refused or stopped before completion')
        content = ''.join(p['text'] for p in candidate['content']['parts'] if not p.get('thought') and 'text' in p)
        usage = data.get('usageMetadata', {})
        usage = {out: usage[src] for src, out in [('promptTokenCount', 'prompt_tokens'),
                 ('candidatesTokenCount', 'completion_tokens'), ('totalTokenCount', 'total_tokens')] if src in usage}
    elif provider == 'anthropic':
        if data.get('stop_reason') == 'max_tokens':
            raise OutputError('was truncated at the output token limit')
        if data['stop_reason'] != 'end_turn' or any(p.get('type') == 'refusal' for p in data['content']):
            raise OutputError('was refused or stopped before completion')
        content = ''.join(p['text'] for p in data['content'] if p.get('type') == 'text')
        raw = data.get('usage', {})
        usage = {'prompt_tokens': raw.get('input_tokens', 0), 'completion_tokens': raw.get('output_tokens', 0)}
        usage['total_tokens'] = sum(v for v in usage.values() if isinstance(v, int))
    else:
        choice = data['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise OutputError('was truncated at the output token limit')
        if choice.get('finish_reason') != 'stop' or choice['message'].get('refusal'):
            raise OutputError('was refused or stopped before completion')
        content, usage = choice['message']['content'], data.get('usage', {})
    return content, {k: v for k, v in usage.items() if k in ('prompt_tokens', 'completion_tokens', 'total_tokens')
                     and isinstance(v, int) and not isinstance(v, bool) and v >= 0}

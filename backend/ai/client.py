"""Bounded provider requests. Never expose vendor error bodies, keys or raw HTTP exceptions."""
import copy
import hashlib
import json
import math
import re
import time
from pathlib import Path

import httpx
from pydantic import ValidationError

from .config import Settings
from .providers import PROVIDERS, ADAPTER_VERSION, request_spec, response_content
from .diagnostics import rejected_output_summary

from .prompts import SYSTEM, TASKS
from .request_limits import REQUEST_LIMITER
from ..operations import CURRENT, check, wait



class ModelError(ValueError):
    pass


def retry_delay(response):
    if response.status_code != 429:
        return .25
    try:
        seconds = float(response.headers.get('retry-after', '2'))
    except ValueError:
        seconds = 2
    if not math.isfinite(seconds) or seconds > 60:
        raise ModelError('Provider rate limit requires a longer wait. This run stopped without upgrading or making further requests.')
    return min(60, max(.25, seconds) + .5)


def provider_error(response, stage, model, api_key, schema=None, provider='groq'):
    """Map provider details to local messages; never echo arbitrary response text."""
    try:
        error = response.json().get('error', {})
    except (ValueError, AttributeError):
        error = {}
    if not isinstance(error, dict):
        error = {}
    code = error.get('code')
    message = error.get('message', '')
    message = message.lower() if isinstance(message, str) else ''
    reasons = {
        'invalid_json_schema': 'The provider rejected the output schema.',
        'json_validate_failed': 'Generated output failed provider JSON/schema validation.',
        'model_not_found': 'The model is unavailable or this account lacks access.',
        'model_decommissioned': 'The configured model was retired; select an available model.',
        'context_length_exceeded': 'The request exceeds the model context limit; reduce the document batch size.',
        'invalid_api_key': 'The API key was rejected; check local credentials.',
        'rate_limit_exceeded': 'The account/model rate limit was reached; wait before retrying.',
        'insufficient_quota': 'The account quota is exhausted; check the provider account.',
    }
    known_code = code if isinstance(code, str) and code in reasons and code != api_key else None
    reason = reasons.get(known_code, {
        400: 'The provider rejected the request; this status alone does not establish a credential or quota problem.',
        401: 'Authentication failed; check local credentials.',
        402: 'Billing or credit access is required; no automatic upgrade or retry was attempted.',
        403: 'Access was denied; check account/model permissions.',
        404: 'The endpoint or model is unavailable.',
        413: 'The request is too large.',
        429: 'A rate or quota limit was reached; check the provider account.',
    }.get(response.status_code, 'The provider could not complete this request.'))
    if not known_code:
        if 'schema' in message:
            reason = 'The provider rejected the output schema or generated output; inspect schema compatibility.'
        elif 'image' in message and any(word in message for word in ('support', 'invalid', 'limit')):
            reason = 'The provider rejected image input; check vision-model support and image limits.'
    # Only predefined parameter names/keywords are exposed, never source text or failed_generation.
    fields = ('response_format', 'max_completion_tokens', 'reasoning_format', 'include_reasoning',
              'image_url', 'minLength', 'maxLength', 'minItems', 'maxItems', 'minimum', 'maximum',
              'additionalProperties', 'required', 'strict')
    hints = [field for field in fields if re.search(r'\b' + re.escape(field.lower()) + r'\b', message)]
    metadata = (' Code: ' + known_code + '.') if known_code else ''
    if hints:
        metadata += ' Referenced request fields: ' + ', '.join(hints) + '.'
    if schema is not None and known_code == 'json_validate_failed':
        metadata += ' Rejected output analysis: ' + json.dumps(rejected_output_summary(error, schema)) + '.'
    safe_model = model if re.fullmatch(r'[A-Za-z0-9_./-]{1,100}', model) and api_key not in model else '[configured model]'
    return ModelError(f'{PROVIDERS[provider]["name"]} request failed (HTTP {response.status_code}; stage={stage}; model={safe_model}). '
                      + reason + metadata + ' Raw provider content withheld. No rule fallback was used.')


class ModelClient:
    def __init__(self, settings=None, transport=None, cache_dir=None, limiter=None):
        self.settings = copy.deepcopy(settings or Settings.load())
        self.transport = transport
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.records = []
        self._pending_cache = None
        # Scripted contract fixtures skip wall-clock waits unless explicitly testing admission.
        self.limiter = limiter if limiter is not None else (None if isinstance(transport, httpx.MockTransport) else REQUEST_LIMITER)

    def complete(self, stage, payload, schema, images=None, pdf=None):
        check()
        operation = CURRENT.get()
        if operation:
            operation.stage = stage
        self._pending_cache = None
        settings = self.settings
        if settings.offline:
            raise ModelError('Model requests are disabled by TERM_AGENT_OFFLINE=1.')
        visual = bool(images or pdf)
        provider = settings.vision_provider if visual else settings.provider
        if provider not in PROVIDERS:
            raise ModelError('Unsupported provider; no request made.')
        key = settings.visual_key() if visual else settings.api_key
        if not key:
            raise ModelError(f'{PROVIDERS[provider]["name"]} key is missing. Save a local key in API settings.')
        if stage not in TASKS or len(self.records) >= settings.max_calls:
            raise ModelError('Unknown stage or per-run model call limit reached. No partial run was marked complete.')
        model = settings.vision_model if visual else settings.model
        if not model:
            raise ModelError('A visual model is required for this content; configure API settings.')
        if pdf and not PROVIDERS[provider]['native_pdf']:
            raise ModelError('This adapter does not support native PDF; select a supported provider or processing mode.')
        if images and not PROVIDERS[provider]['vision']:
            raise ModelError('This adapter does not support image input; select a visual provider.')
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) > 100000:
            raise ModelError('Model payload is too large. Reduce batch size; content was not silently truncated.')
        simulation = isinstance(self.transport, httpx.MockTransport)
        prompt_version = {'discovery': 'discovery-v5-explicit-terms', 'linking': 'linking-v2-compact-refs'}.get(stage, 'prompt-v1')
        identity = json.dumps([stage, provider, model, settings.provenance(), schema.model_json_schema(), payload, images or [], pdf, prompt_version, simulation, ADAPTER_VERSION], sort_keys=True)
        digest = hashlib.sha256(identity.encode()).hexdigest()
        cache = self.cache_dir / (digest + '.json') if self.cache_dir else None
        staged = operation.cache.get(cache) if operation and cache else None
        if staged or cache and cache.is_file():
            try:
                result = schema.model_validate_json(staged or cache.read_text(encoding='utf-8'))
            except (ValidationError, ValueError):
                raise ModelError('Invalid local model cache; remove the affected ai-cache file and retry.') from None
            self.check_credentials(result)
            self.records.append({'stage': stage, 'provider': provider, 'model': model, 'configuration': settings.provenance(), 'request_hash': digest, 'cached': True, 'usage': {}, 'simulation': simulation})
            return result.model_dump()
        prompt = SYSTEM + '\nTASK: ' + TASKS[stage] + '\nJSON schema: ' + json.dumps(schema.model_json_schema())
        output_tokens = min(settings.max_output_tokens, {'boundary_scan': 2048, 'boundary_vision': 3072}.get(stage, settings.max_output_tokens))
        path, headers, body, format_name = request_spec(provider, model, key, stage, prompt, text,
                                                      schema.model_json_schema(), output_tokens, images, pdf)
        strict = provider == 'groq' and body.get('response_format', {}).get('type') == 'json_schema'
        started = time.monotonic()
        format_recovery, transient_retry = False, False
        rate_retries, rate_waited = 0, 0
        request_attempts = 0
        rate_waited_seconds = 0
        rpm = settings.request_rpm(provider, model)
        rejected_outputs = []
        with httpx.Client(base_url=PROVIDERS[provider]['base'], timeout=90, trust_env=False,
                          transport=self.transport, follow_redirects=False) as client:
            # Each format permits two rate waits totaling <=60s, one format recovery and one server retry.
            while True:
                if self.limiter is not None:
                    rate_waited_seconds += self.limiter.acquire(provider, model, rpm)
                check()
                request_attempts += 1
                try:
                    response = client.post(path, headers=headers, json=body)
                except httpx.HTTPError:
                    check()
                    raise ModelError(PROVIDERS[provider]['name'] + ' network/timeout error. Credentials and provider response bodies are withheld.') from None
                check()
                if response.status_code == 429 and rate_retries < 2:
                    delay = retry_delay(response)
                    if rate_waited + delay > 60:
                        raise ModelError('Provider rate-limit wait budget exceeded; no further request sent or account upgrade attempted.')
                    rate_retries += 1
                    rate_waited += delay
                    if self.limiter is not None:
                        self.limiter.defer(provider, model, delay)
                    else:
                        wait(delay)
                    continue
                if response.status_code in (500, 502, 503) and not transient_retry:
                    transient_retry = True
                    wait(retry_delay(response))
                    continue
                if response.status_code == 400 and strict and not format_recovery:
                    try:
                        error = response.json().get('error', {})
                    except (ValueError, AttributeError):
                        error = {}
                    if isinstance(error, dict) and error.get('code') == 'json_validate_failed':
                        rejected_outputs.append(rejected_output_summary(error, schema))
                        # Same model, full input and schema prompt. Local/evidence validation still mandatory.
                        body['response_format'] = {'type': 'json_object'}
                        format_recovery = True
                        rate_retries, rate_waited = 0, 0
                        continue
                if response.status_code != 200:
                    error = provider_error(response, stage, model, key, schema, provider)
                    if format_recovery:
                        raise ModelError(str(error) + ' JSON format recovery was attempted once. Earlier rejected output analysis: '
                                         + json.dumps(rejected_outputs) + '.')
                    raise error
                break
        try:
            data = response.json()
            content, usage = response_content(provider, data)
            if any(secret and secret in content for secret in (settings.api_key, settings.visual_key())):
                raise ModelError('Model output contained credential material and was rejected; contents withheld.')
            result = schema.model_validate_json(content)
            self.check_credentials(result)
        except ModelError:
            raise
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise ModelError('Model response was truncated, refused or failed JSON/schema validation; no partial response or rule fallback was accepted.') from None
        self.records.append({'stage': stage, 'provider': provider, 'model': model, 'configuration': settings.provenance(), 'request_hash': digest, 'cached': False,
                             'usage': usage, 'simulation': simulation, 'response_format': body.get('response_format', {}).get('type', format_name),
                             'format_recovery': format_recovery, 'request_attempts': request_attempts,
                             'rpm_limit': rpm, 'rate_wait_seconds': round(rate_waited_seconds, 3),
                             'reasoning_effort': body.get('reasoning_effort', 'model default'),
                             'max_completion_tokens': output_tokens, 'rejected_outputs': rejected_outputs,
                             'elapsed_seconds': round(time.monotonic() - started, 3)})
        if cache:
            self._pending_cache = (cache, result.model_dump_json())
        return result.model_dump()

    def check_credentials(self, result):
        decoded = result.model_dump_json()
        if any(secret and secret in decoded for secret in (self.settings.api_key, self.settings.visual_key())):
            raise ModelError('Model output contained credential material and was rejected; contents withheld.')

    def accept(self):
        """Cache only after the caller has also checked source evidence and coverage IDs."""
        check()
        if self._pending_cache:
            cache, payload = self._pending_cache
            operation = CURRENT.get()
            if operation:
                operation.cache[cache] = payload
                self._pending_cache = None
                return
            try:
                cache.parent.mkdir(exist_ok=True)
            except FileNotFoundError:
                raise ModelError('The model cache directory no longer exists. No deleted project was recreated.') from None
            cache.write_text(payload, encoding='utf-8')
            self._pending_cache = None


# Compatibility for existing local scripts; all application calls use the common client.
GroqClient = ModelClient

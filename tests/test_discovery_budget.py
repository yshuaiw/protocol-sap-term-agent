import json

import httpx

from backend.ai.client import GroqClient
from backend.ai.config import Settings
from backend.ai.schemas import Extraction, Links
from backend.ai.workflow import document_chunks


def test_many_short_blocks_are_batched_without_losing_any_region():
    blocks = [{'id': str(i), 'region': ('body', 'table', 'header', 'footer', 'footnote')[i % 5],
               'text': 'Arm A'} for i in range(28)]
    chunks = list(document_chunks([{'role': 'Protocol', 'blocks': blocks}], 7000))
    assert len(chunks) == 4 and all(len(chunk) <= 8 for chunk in chunks)
    units = [unit for chunk in chunks for unit in chunk]
    assert [u['block_id'] for u in units] == [b['id'] for b in blocks]
    assert {u['region'] for u in units} == {b['region'] for b in blocks}


def test_chunk_budget_includes_neighbor_context_and_block_metadata():
    blocks = [{'id': str(i), 'region': 'body', 'text': 'a' * 250} for i in range(4)]
    chunks = list(document_chunks([{'role': 'Protocol', 'blocks': blocks}], 1000))
    assert len(chunks) == 4
    assert all(len(chunk) == 1 for chunk in chunks)


def test_long_block_ranges_cover_all_characters_with_overlap():
    text = 'Arm A\n' * 600
    chunks = list(document_chunks([{'role': 'SAP', 'blocks': [{'id': 'long', 'region': 'table', 'text': text}]}], 1000))
    covered = set()
    for chunk in chunks:
        for unit in chunk:
            assert unit['text'] == text[unit['start']:unit['end']]
            covered.update(range(unit['start'], unit['end']))
    assert covered == set(range(len(text)))


def test_low_reasoning_is_scoped_to_gpt_oss_discovery():
    bodies = []
    def reply(request):
        body = json.loads(request.content)
        bodies.append(body)
        content = '{"mentions": []}' if len(bodies) != 2 else '{"assignments": []}'
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]})
    client = GroqClient(Settings(api_key='fixture-key'), transport=httpx.MockTransport(reply))
    client.complete('discovery', {}, Extraction)
    client.complete('linking', {}, Links)
    client.settings.model = 'other-text-model'
    client.complete('discovery', {}, Extraction)
    assert bodies[0]['reasoning_effort'] == 'low'
    assert all('reasoning_effort' not in body for body in bodies[1:])


def test_output_and_chunk_limits_are_locally_configurable(tmp_path, monkeypatch):
    monkeypatch.setenv('TERM_AGENT_CHUNK_UNITS', '3')
    monkeypatch.setenv('TERM_AGENT_MAX_OUTPUT_TOKENS', '8192')
    settings = Settings.load(tmp_path)
    assert settings.chunk_units == settings.public()['chunk_units'] == 3
    assert settings.max_output_tokens == settings.public()['max_output_tokens'] == 8192

import test from 'node:test';
import assert from 'node:assert/strict';
import {sourceSlice} from '../src/sourceText.js';

test('Python Unicode offsets preserve emoji and Chinese around evidence', () => {
  const text = '🙂治疗组：Arm A receives 10 mg.';
  assert.equal(sourceSlice(text, 0, 5), '🙂治疗组：');
  assert.equal(sourceSlice(text, 5, 10), 'Arm A');
  assert.equal(sourceSlice(text, 10), ' receives 10 mg.');
});

test('Ordinary source text keeps the same before/after split', () => {
  const text = 'Visit 1: Arm A.';
  assert.equal(sourceSlice(text, 0, 9), 'Visit 1: ');
  assert.equal(sourceSlice(text, 9, 14), 'Arm A');
  assert.equal(sourceSlice(text, 14), '.');
});

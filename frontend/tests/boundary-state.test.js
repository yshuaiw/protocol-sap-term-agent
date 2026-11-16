import test from 'node:test';
import assert from 'node:assert/strict';
import {boundaryNotice, rangesValid} from '../src/boundaryState.js';

test('A combined file needs valid nonoverlapping ranges before import',()=>{
  const info=[{pages:95}];
  assert.equal(rangesValid([{file_index:0,start:1,end:95},{file_index:0,start:1,end:95}],info),false);
  assert.equal(rangesValid([{file_index:0,start:1,end:60},{file_index:0,start:61,end:95}],info),true);
  assert.equal(rangesValid([{file_index:0,start:1,end:60},{file_index:0,start:61,end:96}],info),false);
});

test('Independent files can each use their full range',()=>{
  assert.equal(rangesValid([{file_index:0,start:1,end:5},{file_index:1,start:1,end:8}],[{pages:5},{pages:8}]),true);
});

test('Empty or embedded-only suggestions never claim ready for review',()=>{
  const no=boundaryNotice([{ai_suggestion:{documents:[]}}]);
  assert.match(no,/No usable independent-document ranges/);
  assert.doesNotMatch(no,/ready for your review/);
  assert.match(boundaryNotice([{ai_suggestion:{documents:[{applicable:false,kind:'embedded_section'}]}}]),/No usable/);
});

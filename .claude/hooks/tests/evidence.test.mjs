import test from 'node:test';
import assert from 'node:assert/strict';
import { evidenceMatches, releaseComplete, assertWorktree, resolveSkill, nextQuestion, supportedExecution } from '../../orchestration/evidence-policy.mjs';
test('custom or version-selected interpreters cannot reuse default environment proof', () => {
  assert.equal(supportedExecution('py -3.12 -m pytest tests -q'), false);
  assert.equal(supportedExecution('C:/venv/Scripts/python.exe -m pytest tests -q'), false);
  assert.equal(supportedExecution('cd backend && py -m pytest tests -q'), true);
});
const identity = { root: '/isolated', head: 'abc', inputs: { 'src/a': 'hash' }, environment: { node: '24', python: '3.12' } };
const evidence = { before: identity, identity, command: 'test', exit_code: 0, result: 'PASS' };
test('wrong worktree is rejected', () => assert.throws(() => assertWorktree('/original', '/isolated')));
test('unchanged evidence is reusable', () => assert.equal(evidenceMatches(evidence, identity), true));
test('content changes invalidate evidence even with same HEAD', () => assert.equal(evidenceMatches(evidence, { ...identity, inputs: { 'src/a': 'changed' } }), false));
test('environment changes invalidate evidence', () => assert.equal(evidenceMatches(evidence, { ...identity, environment: { node: '25' } }), false));
test('missing exit code is not passing evidence', () => assert.equal(evidenceMatches({ ...evidence, exit_code: null }, identity), false));
test('post-only evidence is rejected', () => assert.equal(evidenceMatches({ ...evidence, before: undefined }, identity), false));
test('later failure supersedes a prior pass', () => assert.equal(releaseComplete(['build'], [{ ...evidence, gate: 'build', release: 'r1' }, { ...evidence, gate: 'build', release: 'r1', result: 'FAIL', exit_code: 1 }], identity, 'r1'), false));
test('release requires every gate freshly executed for the release', () => {
  assert.equal(releaseComplete(['build', 'security'], [{ ...evidence, gate: 'build', release: 'r1' }], identity, 'r1'), false);
  assert.equal(releaseComplete(['build'], [{ ...evidence, gate: 'build', release: 'old' }], identity, 'r1'), false);
  assert.equal(releaseComplete(['build'], [{ ...evidence, gate: 'build', release: 'r1' }], identity, 'r1'), true);
});
test('missing and invalid skill references fail closed', () => {
  assert.throws(() => resolveSkill('/missing/SKILL.md'));
  assert.throws(() => resolveSkill(import.meta.filename));
});
test('Grill Me emits only the first unsettled material decision', () => {
  assert.deepEqual(nextQuestion([{ id: 'settled', material: true }, { id: 'minor' }, { id: 'scope', material: true, recommended: 'narrow' }, { id: 'release', material: true }], ['settled']), { id: 'scope', material: true, recommended: 'narrow' });
  assert.equal(nextQuestion([], []), null);
});

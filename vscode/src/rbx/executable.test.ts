import * as assert from 'assert';
import { test } from 'node:test';

import { loginShellProbe, parseLoginShellPath, rbxCandidates } from './executable';

test('without a setting, PATH is tried before the login shell', () => {
  // PATH is free and right whenever VS Code was launched from a shell; the
  // login shell costs a shell startup and is only needed when PATH missed.
  const sources = rbxCandidates(undefined).map((candidate) => candidate.source);
  assert.deepStrictEqual(sources, ['path', 'login-shell']);
});

test('a configured executable is tried first', () => {
  const candidates = rbxCandidates('/opt/rbx/bin/rbx');
  assert.deepStrictEqual(candidates[0], {
    command: '/opt/rbx/bin/rbx',
    source: 'setting',
  });
  // and does not replace the fallbacks, so a bad setting still resolves.
  assert.strictEqual(candidates.length, 3);
});

test('an empty or whitespace setting is treated as unset', () => {
  assert.strictEqual(rbxCandidates('')[0]?.source, 'path');
  assert.strictEqual(rbxCandidates('   ')[0]?.source, 'path');
});

test('the login-shell probe reads profile and rc files', () => {
  const probe = loginShellProbe('/bin/zsh');
  assert.strictEqual(probe.command, '/bin/zsh');
  // -l for the profile, -i because many setups edit PATH in the interactive rc.
  assert.deepStrictEqual(probe.args, ['-lic', 'command -v rbx']);
});

test('parseLoginShellPath ignores rc chatter and takes the path', () => {
  // An interactive login shell prints whatever the user's rc prints.
  const stdout = 'nvm: using v20\nWelcome back!\n/Users/x/.local/bin/rbx\n';
  assert.strictEqual(parseLoginShellPath(stdout), '/Users/x/.local/bin/rbx');
});

test('parseLoginShellPath returns undefined when rbx was not found', () => {
  assert.strictEqual(parseLoginShellPath(''), undefined);
  assert.strictEqual(parseLoginShellPath('rbx not found\n'), undefined);
});

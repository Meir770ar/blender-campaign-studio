import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('./activate_grok_patch.py', import.meta.url), 'utf8');
const transaction = source.split('TRANSACTION = r"""')[1].split('"""')[0];
const targets = ['/app/extensions/xai/video-generation-provider.ts', '/app/dist/video-generation-provider-PMWf4yep.js'];
const hash = x => createHash('sha256').update(x).digest('hex');
function run(states, { rollback = false, failSecondRename = false } = {}) {
  const old = Buffer.from('reviewed original'), fresh = Buffer.from('tested replacement');
  const previous = rollback ? fresh : old, next = rollback ? old : fresh;
  const payload = { files: targets.map(remote => ({ remote, expected_sha256: hash(previous), target_sha256: hash(next), content: next.toString('base64') })) };
  const files = new Map(targets.map((path, index) => [path, states[index] === 'old' ? old : states[index] === 'new' ? fresh : Buffer.from('unrelated changes')]));
  let writes = 0, renames = 0, output, error;
  const fs = { readFileSync: path => path === 0 ? JSON.stringify(payload) : files.get(path),
    statSync: () => ({ mode: 0o644, uid: 1000, gid: 1000 }),
    chownSync: (path, uid, gid) => { assert.equal(uid, 1000); assert.equal(gid, 1000); },
    writeFileSync: (path, data) => { writes++; files.set(path, Buffer.from(data)); },
    renameSync: (from, to) => { renames++; if (failSecondRename && renames === 2) throw new Error('fixture write failure'); files.set(to, files.get(from)); files.delete(from); } };
  try {
    vm.runInNewContext(transaction, { require: name => name === 'fs' ? fs : { createHash }, Buffer,
      process: { pid: 42, exit: () => { throw new Error('test exit'); } },
      console: { log: s => { output = JSON.parse(s); } } });
  } catch (caught) { if (caught.message !== 'test exit') error = caught; }
  return { files, output, writes, error };
}

test('activation replaces only the two verified targets and preserves ownership', () => {
  const result = run(['old', 'old']);
  assert.equal(result.error, undefined); assert.equal(result.output.changed, true);
  assert.ok(targets.every(path => result.files.get(path).toString() === 'tested replacement'));
});
test('known partial activation can be completed or rolled back after interruption', () => {
  assert.equal(run(['new', 'old']).writes, 1);
  const result = run(['new', 'old'], { rollback: true });
  assert.equal(result.writes, 1); assert.equal(result.error, undefined);
  assert.ok(targets.every(path => result.files.get(path).toString() === 'reviewed original'));
});
test('unrelated server changes reject the whole package before writing', () => {
  const result = run(['old', 'unrelated']);
  assert.match(result.error.message, /refusing to overwrite/); assert.equal(result.writes, 0);
});
test('a second-file failure restores the first and fully active package is idempotent', () => {
  const result = run(['old', 'old'], { failSecondRename: true });
  assert.match(result.error.message, /fixture write failure/);
  assert.ok(targets.every(path => result.files.get(path).toString() === 'reviewed original'));
  const complete = run(['new', 'new']);
  assert.equal(complete.writes, 0); assert.equal(complete.output.already_applied, true);
});

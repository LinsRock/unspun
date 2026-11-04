import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

test('bounded public-source collector offline contracts', () => {
  const testsDirectory = fileURLToPath(new URL('../loop/tests/', import.meta.url));
  const result = spawnSync('python3', ['-m', 'unittest', 'discover', '-s', testsDirectory, '-p', 'test_collector.py', '-v'], {
    encoding: 'utf8',
    timeout: 30000,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' },
  });
  assert.equal(result.error, undefined, String(result.error));
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
});

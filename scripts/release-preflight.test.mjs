import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { inspectRelease } from './release-preflight.mjs';

test('release metadata and publication workflow remain aligned', () => {
  const result = inspectRelease(process.cwd());
  assert.equal(result.trigger, 'release.published');
  assert.equal(result.artifact, 'evershelf.zip');
  assert.deepEqual(result.gates, [
    'manifest-changelog',
    'release-workflow',
    'github-release',
    'hacs-policy',
  ]);
});

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'release-preflight-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (const relative of [
    'custom_components/evershelf/manifest.json',
    'hacs.json',
    'CHANGELOG.md',
    '.github/workflows/release.yml',
    '.github/copilot-instructions.md',
    'README.md',
  ]) {
    const target = path.join(root, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(path.join(process.cwd(), relative), target);
  }
  return root;
}

test('release preflight rejects stale leading changelog metadata', t => {
  const root = fixture(t);
  fs.writeFileSync(path.join(root, 'CHANGELOG.md'),
    fs.readFileSync(path.join(root, 'CHANGELOG.md'), 'utf8')
      .replace(/^## \[\d+\.\d+\.\d+\]/m, '## [0.0.0]'));
  assert.throws(() => inspectRelease(root), /first changelog release/);
});

test('release preflight rejects missing explicit HACS install guidance', t => {
  const root = fixture(t);
  fs.writeFileSync(path.join(root, 'README.md'),
    fs.readFileSync(path.join(root, 'README.md'), 'utf8')
      .replace('### Step 1 — Add via HACS', '### Installation')
      .replace('click **Download**', 'install it'));
  assert.throws(() => inspectRelease(root), /explicit HACS install paths/);
});

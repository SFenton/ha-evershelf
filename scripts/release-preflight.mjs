#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

export function inspectRelease(root) {
  const read = relative => fs.readFileSync(path.join(root, relative), 'utf8');
  const manifest = JSON.parse(read('custom_components/evershelf/manifest.json'));
  const hacs = JSON.parse(read('hacs.json'));
  const changelog = read('CHANGELOG.md');
  const workflow = read('.github/workflows/release.yml');
  const instructions = read('.github/copilot-instructions.md');
  const readme = read('README.md');

  assert(/^\d+\.\d+\.\d+$/.test(manifest.version), 'manifest version must be semantic');
  const firstRelease = changelog.match(/^## \[(\d+\.\d+\.\d+)\]/m)?.[1];
  assert(firstRelease === manifest.version,
    'the first changelog release must match the manifest version');
  assert(/on:\s*\n\s+release:\s*\n\s+types:\s*\n\s+- published/m.test(workflow),
    'release workflow must run on published releases');
  assert(workflow.includes('zip -r ../evershelf.zip evershelf/'),
    'release workflow must package only the integration directory');
  assert(workflow.includes('softprops/action-gh-release@v2') &&
    workflow.includes('files: evershelf.zip'),
  'release workflow must upload evershelf.zip to the GitHub Release');
  assert(hacs.content_in_root === false && hacs.render_readme === true,
    'HACS metadata must use the integration subdirectory and repository README');
  assert(/pushed tags alone|tag without a GitHub Release/i.test(instructions) &&
    /HACS/i.test(instructions),
    'release policy must reject tag-only completion and require HACS visibility');
  assert(readme.includes('github.com/SFenton/ha-evershelf/releases') &&
    readme.includes('github.com/SFenton/ha-evershelf/releases/latest') &&
    !readme.includes('github.com/dadaloop82/ha-evershelf') &&
    /Add via HACS/i.test(readme) &&
    /click \*\*Download\*\*/i.test(readme),
  'README must retain the SFenton GitHub Release and explicit HACS install paths');

  return {
    version: manifest.version,
    package: 'custom_components/evershelf',
    trigger: 'release.published',
    artifact: 'evershelf.zip',
    gates: ['manifest-changelog', 'release-workflow', 'github-release', 'hacs-policy'],
  };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
    console.log(JSON.stringify(inspectRelease(process.cwd()), null, 2));
  } catch (error) {
    console.error(`release-preflight: ${error.message}`);
    process.exitCode = 1;
  }
}

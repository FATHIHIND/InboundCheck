import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const lock = JSON.parse(await readFile(new URL('../../package-lock.json', import.meta.url), 'utf8'));

test('macOS optional fsevents is explicitly locked with verified registry integrity', () => {
  assert.equal(lock.packages['node_modules/chokidar'].optionalDependencies.fsevents, '~2.3.2');
  const entry = lock.packages['node_modules/fsevents'];
  assert.ok(entry, 'Do not omit incompatible-host optional packages from the cross-platform lock');
  assert.equal(entry.version, '2.3.3');
  assert.deepEqual(entry.os, ['darwin']);
  assert.equal(entry.optional, true);
  assert.equal(entry.hasInstallScript, true);
  assert.equal(entry.resolved, 'https://registry.npmjs.org/fsevents/-/fsevents-2.3.3.tgz');
  // Tarball bytes independently checked against official npm metadata.
  assert.equal(entry.integrity, 'sha512-5xoDfX+fL7faATnagmWPpbFtwh/R77WmMMqqHGS65C3vvB0YHrgF+B1YmZ3441tMj5n63k0212XNoJwzlhffQw==');
});

test('all optional dependency names resolve to entries in the workspace lock', () => {
  for (const [parent, entry] of Object.entries(lock.packages)) {
    for (const dependency of Object.keys(entry.optionalDependencies || {})) {
      let location = parent;
      let found = false;
      while (true) {
        const candidate = location ? `${location}/node_modules/${dependency}` : `node_modules/${dependency}`;
        if (lock.packages[candidate]) { found = true; break; }
        if (!location) break;
        const index = location.lastIndexOf('/node_modules/');
        location = index >= 0 ? location.slice(0, index) : '';
      }
      assert.ok(found, `${parent}: missing optional dependency ${dependency}`);
    }
  }
});


test('framework security upgrade stays pinned and lock contains authenticated npm artifacts', async () => {
  const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(manifest.dependencies.next, '16.4.5');
  assert.equal(manifest.dependencies.react, '19.3.1');
  assert.equal(manifest.dependencies['react-dom'], '19.3.1');
  assert.equal(manifest.devDependencies['eslint-config-next'], '16.4.5');
  assert.equal(manifest.devDependencies.eslint, '10.14.0');
  for (const name of ['next', 'react', 'react-dom']) {
    const entry = lock.packages['frontend/node_modules/'+name] || lock.packages['node_modules/'+name];
    assert.equal(entry.version, manifest.dependencies[name]);
    assert.ok(entry.resolved.startsWith('https://registry.npmjs.org/'));
    assert.ok(entry.integrity.startsWith('sha512-'));
  }
  assert.equal(manifest.overrides, undefined, 'Do not bypass upstream dependency constraints to hide advisories');
});


test('framework migration preserves unrelated direct dependency resolutions and original ranges', async () => {
  const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  const expected = {
    '@designcodeio/threeui': ['1.1.0', '^1.1.0'],
    '@supabase/ssr': ['0.12.4', '^0.12.4'],
    '@supabase/supabase-js': ['2.112.3', '^2.43.4'],
    'framer-motion': ['13.1.1', '^13.1.1'],
  };
  for (const [name, [version, range]] of Object.entries(expected)) {
    const entries = Object.entries(lock.packages).filter(([location]) => location.endsWith('node_modules/' + name));
    assert.ok(entries.length > 0, 'Missing '+name);
    for (const [, entry] of entries) assert.equal(entry.version, version, name);
    assert.equal(manifest.dependencies[name], range, name + ' manifest range');
    assert.equal(lock.packages.frontend.dependencies[name], range, name + ' lock workspace range');
  }
});

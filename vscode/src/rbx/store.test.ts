import * as assert from 'assert';
import { test } from 'node:test';

import { packageLayout } from './layout';
import { ArtifactStore, ArtifactStores } from './store';

class CountingStore extends ArtifactStore {
  invalidations = 0;

  override invalidate(): void {
    this.invalidations += 1;
    super.invalidate();
  }
}

function registry(): ArtifactStores {
  return new ArtifactStores((pkg) => new CountingStore(pkg));
}

test('the same layout gets the same store, so its cache survives', () => {
  const stores = registry();
  const first = stores.for(packageLayout('/pkg', 'build'));

  assert.strictEqual(stores.for(packageLayout('/pkg', 'build')), first);
});

test('a moved build directory gets a fresh store over the new layout', () => {
  // The preset renamed `build` to `build.rbx`: a store found by root alone
  // would keep reading the old directory until the window was reloaded.
  const stores = registry();
  const stale = stores.for(packageLayout('/pkg', 'build'));

  const fresh = stores.for(packageLayout('/pkg', 'build.rbx'));

  assert.notStrictEqual(fresh, stale);
  assert.deepStrictEqual(fresh.pkg, packageLayout('/pkg', 'build.rbx'));
  assert.strictEqual(stores.for(packageLayout('/pkg', 'build.rbx')), fresh);
});

test('rediscovery forgets moved and vanished packages and invalidates the rest', () => {
  const stores = registry();
  const kept = stores.for(packageLayout('/a', 'build')) as CountingStore;
  const moved = stores.for(packageLayout('/b', 'build'));
  const gone = stores.for(packageLayout('/c', 'build'));

  stores.retain([packageLayout('/a', 'build'), packageLayout('/b', 'out')]);

  assert.strictEqual(stores.for(packageLayout('/a', 'build')), kept);
  assert.strictEqual(kept.invalidations, 1);
  assert.notStrictEqual(stores.for(packageLayout('/b', 'out')), moved);
  assert.notStrictEqual(stores.for(packageLayout('/c', 'build')), gone);
});

test('invalidating a package with no store is a no-op', () => {
  const stores = registry();
  const store = stores.for(packageLayout('/a', 'build')) as CountingStore;

  stores.invalidate('/elsewhere');
  stores.invalidate('/a');

  assert.strictEqual(store.invalidations, 1);
});

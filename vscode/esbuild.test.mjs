/**
 * Compile the `*.test.ts` files (and what they import) so `node --test` can run
 * them.
 *
 * Separate from esbuild.mjs because the extension bundle has a single entry
 * point and externalizes `vscode`; the tests have one entry point per file and
 * must never reach the `vscode` module at all -- which is the point of keeping
 * the logic they cover in plain modules.
 */
import { readdirSync } from 'node:fs';

import * as esbuild from 'esbuild';

// `readdirSync({recursive})` rather than `fs.globSync`, which only exists from
// Node 22 and this repo does not pin a Node that new.
const entryPoints = readdirSync('src', { recursive: true })
  .map(String)
  .filter((name) => name.endsWith('.test.ts'))
  .map((name) => `src/${name}`);
if (entryPoints.length === 0) {
  throw new Error('No test files found under src/.');
}

await esbuild.build({
  entryPoints,
  bundle: true,
  format: 'cjs',
  platform: 'node',
  target: 'node18',
  outdir: 'out-test',
  outbase: 'src',
  sourcemap: 'inline',
  logLevel: 'info',
});

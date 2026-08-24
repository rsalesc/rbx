import * as fs from 'node:fs';

import * as esbuild from 'esbuild';

const production = process.argv.includes('--production');
const watch = process.argv.includes('--watch');

const shared = {
  bundle: true,
  minify: production,
  sourcemap: !production,
  sourcesContent: false,
  logLevel: 'info',
};

const extension = await esbuild.context({
  ...shared,
  entryPoints: ['src/extension.ts'],
  format: 'cjs',
  platform: 'node',
  target: 'node18',
  outfile: 'dist/extension.js',
  external: ['vscode'],
});

// The webview client is a separate bundle because it runs in a browser, not in
// Node, and must never reach the `vscode` module -- it talks to the host only
// through `acquireVsCodeApi`.
const webview = await esbuild.context({
  ...shared,
  entryPoints: [
    'src/webview/main.ts',
    'src/webview/testsetMain.ts',
    'src/webview/panelMain.ts',
    'src/webview/style.css',
    'src/webview/panelStyle.css',
  ],
  format: 'iife',
  platform: 'browser',
  target: 'es2020',
  outdir: 'dist/webview',
  // `style.css` points its `@font-face` at the copied `codicon.ttf`, which
  // exists next to the output rather than in the source tree: the url has to
  // survive bundling untouched instead of being resolved at build time.
  external: ['*.ttf'],
});

// The codicon font and its stylesheet are copied rather than referenced from
// `node_modules`, which is not in the shipped vsix. The upstream stylesheet is
// shipped whole on purpose: it carries the icon-name -> code-point table, and a
// hand-written copy of it would draw the *wrong* glyph when it drifted.
fs.mkdirSync('dist/webview', { recursive: true });
for (const name of ['codicon.css', 'codicon.ttf']) {
  fs.cpSync(`node_modules/@vscode/codicons/dist/${name}`, `dist/webview/${name}`);
}

if (watch) {
  await Promise.all([extension.watch(), webview.watch()]);
} else {
  await Promise.all([extension.rebuild(), webview.rebuild()]);
  await Promise.all([extension.dispose(), webview.dispose()]);
}

/**
 * Lint rules for the extension.
 *
 * `npm run lint` has existed since the extension was scaffolded but had neither
 * a config nor the dependency to run it, so it only ever failed with
 * `eslint: command not found`. This is that script made real.
 *
 * Type-aware rules are on. The interesting mistakes in this codebase are about
 * types the compiler already knows -- a floating promise in an activation path,
 * an `any` escaping a YAML parse -- and none of those are visible to the
 * syntactic rules alone. `wire.ts` exists precisely because everything read off
 * disk arrives as `unknown`, and these rules are what keep that boundary from
 * leaking inward.
 *
 * Formatting is deliberately not linted: nothing in the repo formats TypeScript
 * (ruff covers the Python side only), and adopting a style ruleset now would
 * bury real findings under a reformat of every file.
 */
import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config([
  // Build output and the compiled tests, none of which are sources.
  { ignores: ['dist/', 'out/', 'out-test/'] },
  js.configs.recommended,
  tseslint.configs.recommendedTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    // The build scripts are plain ESM run by node, outside the tsconfig the
    // type-aware rules resolve against, and they use node globals directly.
    files: ['**/*.mjs'],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['**/*.test.ts'],
    rules: {
      // `test()` from node:test returns a promise that the test runner awaits;
      // the caller is not supposed to. Left on everywhere else, where an
      // unawaited promise is a real bug.
      '@typescript-eslint/no-floating-promises': 'off',
    },
  },
]);

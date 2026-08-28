/**
 * Reading `rbx vars --json`.
 *
 * Every malformed shape resolves to `undefined` rather than throwing: the
 * feature degrades to "no badges", never to an error the user has to dismiss.
 *
 * Pure: no `vscode` import, so `node --test` covers it directly.
 */
import { Vars } from './statementVars';

/**
 * The payload's own text, with whatever printed before it dropped.
 *
 * rbx emits the object on a line of its own, but it is not necessarily the
 * first line: a shell wrapper, a venv activation or a deprecation warning can
 * print first, and that noise may itself contain a brace. So each `{` is tried
 * in turn until one starts something that parses -- but only a *syntax* error
 * moves on to the next. A payload that parses and then turns out to be the
 * wrong shape is the CLI's answer, and looking deeper into it would find the
 * inner map of `{"a": {"b": "1"}}` and badge a var no statement can name.
 *
 * Only *leading* noise is tolerated. Anything printed after the object makes
 * the slice fail to parse, and every later `{` starts even further inside it,
 * so the payload is dropped whole. That is a considered limit rather than an
 * oversight: rbx prints the object last, trailing output would mean something
 * wrote over its stdout, and under D5 no badges beats guessing which half of
 * the stream was the answer.
 */
function parseLeadingObject(stdout: string): unknown {
  for (let start = stdout.indexOf('{'); start >= 0; start = stdout.indexOf('{', start + 1)) {
    try {
      return JSON.parse(stdout.slice(start));
    } catch {
      continue;
    }
  }
  return undefined;
}

export function parseVarsPayload(stdout: string): Vars | undefined {
  const parsed = parseLeadingObject(stdout);
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return undefined;
  }

  // Deliberately out here, not inside `parseLeadingObject`'s loop: a shape
  // mismatch must end the read, not resume the scan. Retrying from the next
  // brace would step *into* `{"a": {"b": "1"}}` and accept the inner map.
  const entries = Object.entries(parsed as Record<string, unknown>);
  if (!entries.every(([, value]) => typeof value === 'string')) {
    return undefined;
  }
  // `fromEntries` *defines* each key, so a var named `__proto__` lands as an
  // own property rather than being swallowed by the prototype setter, and the
  // result's prototype is left alone. `statementVars.ts` looks names up with
  // `Object.hasOwn`, so that is exactly what it needs to find.
  return Object.fromEntries(entries) as Vars;
}

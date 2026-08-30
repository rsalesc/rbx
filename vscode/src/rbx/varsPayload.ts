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
 * Terminal escape sequences are stripped first, because rbx really does emit
 * one after the payload: Rich restores the cursor on exit, so stdout ends
 * `}\n\x1b[?25h` whenever `FORCE_COLOR` is set in the environment the editor
 * inherited. That is invisible in a terminal and fatal to `JSON.parse`, and it
 * depends on how the user launched their editor rather than on anything the
 * extension does -- exactly the kind of failure that would present as "the
 * feature does nothing on my machine".
 *
 * Other *trailing* noise is still not tolerated. Anything else printed after
 * the object makes the slice fail to parse, and every later `{` starts further
 * inside it, so the payload is dropped whole. That remains a considered limit:
 * rbx prints the object last, so trailing text would mean something wrote over
 * its stdout, and under D5 no badges beats guessing which half of the stream
 * was the answer.
 */
const ANSI_ESCAPE = /\u001b\[[0-9;?]*[ -\/]*[@-~]/g;

function parseLeadingObject(raw: string): unknown {
  const stdout = raw.replace(ANSI_ESCAPE, '');
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

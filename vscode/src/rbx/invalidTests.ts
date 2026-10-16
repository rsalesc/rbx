/**
 * What to tell the user when a run they started from the editor went ahead past
 * testcases that failed validation (`--on-invalid=warn`).
 *
 * The Run view already flags them, but a run started from a CodeLens may finish
 * with the view closed -- and a verdict on an invalid testcase is exactly the
 * kind of result that should not be taken at face value without knowing it.
 *
 * Imports only types: the Run view's webview bundle reaches this module through
 * viewModel.ts, and model.ts itself needs Node's `path`.
 */
import type { InvalidTestcase, RunValidation } from './model';

/** `group/index`, the key a run's rejections are looked up by. */
export function invalidKey(group: string, index: number): string {
  return `${group}/${index}`;
}

/** The rejections of a run, per testcase. */
export function invalidByTestcase(
  validation: RunValidation | undefined,
): ReadonlyMap<string, readonly InvalidTestcase[]> {
  const byTestcase = new Map<string, InvalidTestcase[]>();
  for (const invalid of validation?.invalid ?? []) {
    const key = invalidKey(invalid.group, invalid.index);
    byTestcase.set(key, [...(byTestcase.get(key) ?? []), invalid]);
  }
  return byTestcase;
}

/** The notification for a finished run, or undefined when it needs none. */
export function invalidTestsMessage(validation: RunValidation | undefined): string | undefined {
  const byTestcase = invalidByTestcase(validation);
  if (byTestcase.size === 0) {
    return undefined;
  }
  const names = [...byTestcase.keys()];
  const shown = names.slice(0, 3).join(', ');
  const rest = names.length > 3 ? ` and ${names.length - 3} more` : '';
  const count = names.length === 1 ? '1 testcase' : `${names.length} testcases`;
  return (
    `rbx: ${count} failed validation (${shown}${rest}); the run went ahead anyway. ` +
    'Verdicts on them are on inputs the problem never promises to give.'
  );
}

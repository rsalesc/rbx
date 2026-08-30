/**
 * Which filtered references a document still has to ask rbx about.
 *
 * Pure: no `vscode` import, so `node --test` covers it directly. It lives here
 * rather than beside the scanner because the scanner answers "what does this
 * text reference", which is a question about the text alone; this answers "what
 * is left to render", which is a question about the text *and* what has already
 * come back.
 */
import { VarHint } from './statementVars';

/**
 * The expressions of `hints` that no rendered text is known for yet.
 *
 * Unfiltered hints are never here: their text came with the bulk var map and
 * costs no render. The result is deduplicated, keeping first-appearance order,
 * because a statement repeats a bound as often as it states one and a batch
 * should carry it once.
 *
 * `rendered` holds only the expressions that came back *with* text. One that
 * rbx declined to render is therefore returned again on the next call -- that
 * is deliberate, and it is not a re-spawn: the cache behind `renderedFor`
 * remembers having asked, so a repeat of an expression it already failed is
 * answered from memory. Keeping that knowledge out of here is what lets this
 * function stay a question about *text*, with one map to consult rather than
 * two.
 */
export function pendingRenders(
  hints: readonly VarHint[],
  rendered: ReadonlyMap<string, string>,
): string[] {
  const pending: string[] = [];
  const seen = new Set<string>();
  for (const hint of hints) {
    if (!hint.filtered || rendered.has(hint.expression) || seen.has(hint.expression)) {
      continue;
    }
    seen.add(hint.expression);
    pending.push(hint.expression);
  }
  return pending;
}

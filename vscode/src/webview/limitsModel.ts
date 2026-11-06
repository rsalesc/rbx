/**
 * The time-profile client's pure logic, kept out of limitsMain.ts so it can be
 * tested without a DOM.
 */
import type { InspectResult, Row } from '../rbx/limitsInspect';
import type { NavInfo, NavProblem, ViewState } from './limitsRender';

/**
 * rbx's last answer with every optimistic limit laid over it: the value the
 * setter is dragging or stepping shows at once, while the checks beside it are
 * marked as a step behind (`updating`) until rbx answers for it.
 */
export function withOptimistic(state: ViewState, optimistic: ReadonlyMap<string, number>): ViewState {
  const result = state.result;
  if (result === undefined || optimistic.size === 0) return state;
  const rows: Row[] | undefined = result.rows?.map((row) =>
    optimistic.has(row.key) ? { ...row, timeLimit: optimistic.get(row.key) ?? row.timeLimit } : row,
  );
  const patched: InspectResult = {
    ...result,
    rows,
    timeLimit: optimistic.has('base') ? optimistic.get('base') : result.timeLimit,
  };
  return { ...state, result: patched, updating: true };
}

/**
 * Whether a state from the host lets the optimistic values go: rbx is idle and
 * has answered for every edit sent. An answer to an older edit arriving while
 * a newer one is on its way must not snap the limit back.
 */
export function canDropOptimistic(state: ViewState, sentSeq: number, dragging: boolean): boolean {
  return !state.updating && (state.seq ?? 0) >= sentSeq && !dragging;
}

/** A limit as the ± buttons and the drag produce it: a positive multiple of `step`. */
export function snapLimit(ms: number, step: number): number {
  return Math.max(step, Math.round(ms / step) * step);
}

/**
 * The problem `delta` steps away among those that have a profile, wrapping
 * around; undefined when there is nowhere else to go.
 */
export function stepProblem(nav: NavInfo, delta: number): NavProblem | undefined {
  const candidates = nav.problems.filter((p) => p.profiles.length > 0 || p.root === nav.root);
  const index = candidates.findIndex((p) => p.root === nav.root);
  if (index < 0 || candidates.length < 2) return undefined;
  let next = index;
  do {
    next = (next + delta + candidates.length) % candidates.length;
  } while (candidates[next].profiles.length === 0 && next !== index);
  return next === index ? undefined : candidates[next];
}

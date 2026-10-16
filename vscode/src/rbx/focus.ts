/**
 * Which packages the extension spends processes on.
 *
 * Discovery is a glob and costs nothing per package; asking rbx about one costs
 * a Python interpreter. A workspace can hold thousands of packages -- a repo
 * whose git worktrees each carry their own copy of every test problem -- and
 * asking about all of them at once has taken a whole machine down. So the
 * eager askers (the Assets view, the statement listing) ask only inside the
 * focus: the contest the selected problem belongs to, every problem of it, or
 * the selected problem alone when it is in no contest.
 *
 * Contest variants need nothing extra: they are sibling files in the same
 * contest root, so the focus that holds the contest holds all of them.
 */
import * as path from 'path';

export interface Focus {
  /** The contest root of the selected problem, if it is in one. */
  readonly contest?: string;
  /** The problem roots inside the focus, sorted. */
  readonly problems: readonly string[];
}

export const EMPTY_FOCUS: Focus = { problems: [] };

/**
 * The discovered problems that may belong to `contest`: the ones at or under
 * its directory.
 *
 * Only *may*: a nested `contest.rbx.yml` further down claims its own subtree,
 * which the caller settles with the same upward walk rbx makes. Narrowing by
 * path first is what keeps that walk to a contest's dozen problems rather than
 * every package in the workspace.
 */
export function focusCandidates(contest: string, problems: readonly string[]): string[] {
  const prefix = contest.endsWith(path.sep) ? contest : contest + path.sep;
  return problems.filter((root) => root === contest || root.startsWith(prefix)).sort();
}

/**
 * Whether two foci hold the same packages.
 *
 * Moving between problems of one contest leaves the focus where it was, and
 * must not reload every listing in it.
 */
export function sameFocus(a: Focus, b: Focus): boolean {
  return (
    a.contest === b.contest &&
    a.problems.length === b.problems.length &&
    a.problems.every((root, i) => root === b.problems[i])
  );
}

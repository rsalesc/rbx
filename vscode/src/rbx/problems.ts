/**
 * The problems the selector offers, in the order it offers them.
 *
 * Pure: the caller supplies the roots, the contest identities and a fallback
 * labeller, because naming a package with no contest needs `vscode.workspace`
 * to say which folder it sits in -- and this module's value is being testable
 * without the editor API. Same split as `PackageRunView.label`.
 */
import * as path from 'path';

import { ProblemIdentity } from './contest';

/** One entry in the dropdown. */
export interface ProblemChoice {
  readonly root: string;
  readonly label: string;
  /** The contest this belongs to, for `<optgroup>`. Absent when there is one group. */
  readonly group?: string;
  readonly color?: string;
}

/** How a package with no contest is named. Supplied by the host. */
export type FallbackLabel = (root: string) => string;

interface Entry {
  readonly root: string;
  readonly label: string;
  readonly color?: string;
  readonly group?: string;
  readonly order: number;
}

/**
 * Order two strings by code unit, the way a bare `Array.prototype.sort` does.
 *
 * Not `localeCompare`: it answers by locale and can call two distinct strings
 * equal, which is exactly what the tie-breaks below exist to rule out. Plain
 * comparison also keeps this in step with `discovery.ts`, which hands over
 * roots already sorted that way.
 */
function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

export function problemChoices(
  roots: readonly string[],
  identities: ReadonlyMap<string, ProblemIdentity>,
  fallback: FallbackLabel,
): ProblemChoice[] {
  const contested: Entry[] = [];
  const loose: Entry[] = [];
  for (const root of roots) {
    const identity = identities.get(root);
    if (identity === undefined) {
      loose.push({ root, label: fallback(root), order: 0 });
    } else {
      contested.push({
        root,
        label: identity.shortName,
        color: identity.color,
        // The contest that named the problem, not the problem's parent: a
        // contest may nest its problems, and the intermediate directory is
        // neither the contest's name nor unique across contests.
        group: identity.contestRoot,
        order: identity.order,
      });
    }
  }

  contested.sort((a, b) => {
    const group = compare(a.group ?? '', b.group ?? '');
    if (group !== 0) {
      return group;
    }
    // `order` is counted per contest file, and `indexContests` merges a
    // dispatcher's variants (`contest.div1.rbx.yml`, `contest.div2.rbx.yml`)
    // into one index, so two problems in the same group really can both claim
    // order 1. Falling through to the label and then the root keeps the
    // dropdown from reshuffling with whatever order discovery happened to
    // yield -- these tie-breaks are not redundant.
    return a.order - b.order || compare(a.label, b.label) || compare(a.root, b.root);
  });
  loose.sort((a, b) => compare(a.root, b.root));

  // One group is no grouping: an `<optgroup>` wrapping every option says
  // nothing and costs a row of chrome in a narrow sidebar.
  const groups = new Set(contested.map((entry) => entry.group));
  const grouped = groups.size > 1;

  return [...contested, ...loose].map((entry) => ({
    root: entry.root,
    label: entry.label,
    color: entry.color,
    group: grouped && entry.group !== undefined ? path.basename(entry.group) : undefined,
  }));
}

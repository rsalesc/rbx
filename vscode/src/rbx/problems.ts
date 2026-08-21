/**
 * The problems the selector offers, in the order it offers them.
 *
 * Pure: the caller supplies the roots, the contest identities and a fallback
 * labeller, because naming a package with no contest needs `vscode.workspace`
 * to say which folder it sits in -- and this module's value is being testable
 * without the editor API. Same split as `PackageRunView.label`.
 *
 * `roots` is taken as already de-duplicated: a repeated root becomes a repeated
 * choice. `discovery.ts` collects them through a `Set`, and keeping the rule on
 * that side leaves this module free of an opinion about identity.
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

/** A package a contest named: it always has a contest to group under. */
interface ContestedEntry {
  readonly root: string;
  readonly label: string;
  readonly color?: string;
  readonly group: string;
  readonly order: number;
}

/** A package no contest named: nothing orders it but its own path. */
interface LooseEntry {
  readonly root: string;
  readonly label: string;
  readonly color?: string;
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

/**
 * Order two contests the way their headings read.
 *
 * By basename first, because that is the whole of what the `<optgroup>` shows:
 * ordering by the full root would print `beta` above `alpha` for `/z/alpha` and
 * `/a/beta`. The full root then settles two contests in same-named directories,
 * whose headings collide anyway but must at least not shuffle.
 */
function compareGroups(a: string, b: string): number {
  return compare(path.basename(a), path.basename(b)) || compare(a, b);
}

export function problemChoices(
  roots: readonly string[],
  identities: ReadonlyMap<string, ProblemIdentity>,
  fallback: FallbackLabel,
): ProblemChoice[] {
  const contested: ContestedEntry[] = [];
  const loose: LooseEntry[] = [];
  for (const root of roots) {
    const identity = identities.get(root);
    if (identity === undefined) {
      loose.push({ root, label: fallback(root) });
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
    const group = compareGroups(a.group, b.group);
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
  // nothing and costs a row of chrome in a narrow sidebar. The loose packages
  // count as a group of their own even though they render without a heading --
  // a contest sitting flush against a run of bare folder names is the case a
  // heading most needs to explain.
  const groups = new Set(contested.map((entry) => entry.group));
  const grouped = groups.size + (loose.length > 0 ? 1 : 0) > 1;

  return [...contested, ...loose].map((entry) => ({
    root: entry.root,
    label: entry.label,
    color: entry.color,
    // `group` is absent on every loose entry, so this both narrows the union
    // and leaves the loose run headingless.
    group: grouped && 'group' in entry ? path.basename(entry.group) : undefined,
  }));
}

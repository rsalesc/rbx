/**
 * The problems the selector offers, in the order it offers them.
 *
 * Pure: the caller supplies the roots, the contest identities and a fallback
 * labeller, because naming a package with no contest needs `vscode.workspace`
 * to say which folder it sits in -- and this module's value is being testable
 * without the editor API.
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

/**
 * What a package calls itself, when it says so. Supplied by the host.
 *
 * Injected rather than read here for the same reason as `FallbackLabel`:
 * reaching the manifest means touching the disk, and this module's value is
 * being decidable without it.
 */
export type ProblemName = (root: string) => string | undefined;

/** Separates the contest letter from the problem's own name. */
const NAME_SEPARATOR = ' · ';

/** A package a contest named: it always has a contest to group under. */
interface ContestedEntry {
  readonly root: string;
  readonly label: string;
  readonly color?: string;
  /** Orders the groups and decides where one ends; never shown. */
  readonly groupKey: string;
  /** What the `<optgroup>` heading reads; never ordered by. */
  readonly groupLabel: string;
  readonly order: number;
}

/**
 * The two halves of a group: what sorts it, and what it reads as.
 *
 * One string used to do both, back when a group was a contest root and its
 * heading was that root's basename. A variant's heading now names the variant
 * too, and the id sorts differently from the text around it, so the sort key
 * has to stay the raw pair.
 */
function groupOf(identity: ProblemIdentity): { key: string; label: string } {
  const base = path.basename(identity.contestRoot);
  return identity.variantId === undefined
    ? // The canonical's empty id sorts before every valid one (they must start
      // with a letter), which is what puts its block first without a special
      // case. The separator keeps `/a` + `bc` from keying the same as `/ab` +
      // `c`, neither of which can contain it.
      { key: `${identity.contestRoot}\u0000`, label: base }
    : {
        key: `${identity.contestRoot}\u0000${identity.variantId}`,
        label: `${base} (${identity.variantId})`,
      };
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
 * Order two groups the way their headings read.
 *
 * By the key's last segment first, because that is the contest directory's own
 * name -- what heads the `<optgroup>` -- with the variant id after the NUL:
 * ordering by the whole key would print `beta` above `alpha` for `/z/alpha` and
 * `/a/beta`. Since the NUL sorts below every character a name may hold, this
 * one comparison orders by contest name and then by variant, which is what puts
 * `c` before `c2` and the canonical `c` before `c (div2)` alike.
 *
 * The whole key then settles two contests in same-named directories, whose
 * headings collide anyway but must at least not shuffle.
 *
 * Variants sort among themselves by id, which is the filename order
 * `contestFiles` merged in, so the blocks read in the order first-wins
 * resolved them.
 */
function compareGroups(a: string, b: string): number {
  return compare(path.basename(a), path.basename(b)) || compare(a, b);
}

export function problemChoices(
  roots: readonly string[],
  identities: ReadonlyMap<string, ProblemIdentity>,
  fallback: FallbackLabel,
  name: ProblemName = () => undefined,
): ProblemChoice[] {
  const contested: ContestedEntry[] = [];
  const loose: LooseEntry[] = [];
  for (const root of roots) {
    const identity = identities.get(root);
    if (identity === undefined) {
      loose.push({ root, label: fallback(root) });
    } else {
      // The letter carries the ordering and the contest's own vocabulary; the
      // name says which problem it actually is. A package that declares no
      // name keeps the bare letter rather than growing an empty separator.
      const declared = name(root);
      // The contest file that named the problem, not the problem's parent: a
      // contest may nest its problems, so the root's parent directory is
      // neither the contest's name nor unique across contests.
      const group = groupOf(identity);
      contested.push({
        root,
        label:
          declared === undefined
            ? identity.shortName
            : `${identity.shortName}${NAME_SEPARATOR}${declared}`,
        color: identity.color,
        groupKey: group.key,
        groupLabel: group.label,
        order: identity.order,
      });
    }
  }

  contested.sort((a, b) => {
    const group = compareGroups(a.groupKey, b.groupKey);
    if (group !== 0) {
      return group;
    }
    // A group is one contest file and `order` is counted per file, so within a
    // group it decides outright -- a dispatcher's variants no longer share one.
    // The tie-breaks stay for the file that names one directory twice, where
    // `problemIdentities` keeps the first block's letter but the second entry
    // still counted an order of its own.
    return a.order - b.order || compare(a.label, b.label) || compare(a.root, b.root);
  });
  loose.sort((a, b) => compare(a.root, b.root));

  // One group is no grouping: an `<optgroup>` wrapping every option says
  // nothing and costs a row of chrome in a narrow sidebar. The loose packages
  // count as a group of their own even though they render without a heading --
  // a contest sitting flush against a run of bare folder names is the case a
  // heading most needs to explain.
  const groups = new Set(contested.map((entry) => entry.groupKey));
  const grouped = groups.size + (loose.length > 0 ? 1 : 0) > 1;

  // Mapped per array rather than over the concatenation: only a contested
  // entry has a contest to head, and two maps say so outright. Narrowing the
  // union back apart with `'group' in entry` would not even work -- since TS
  // 4.9 that widens the loose half to `Record<'group', unknown>` on the true
  // branch instead of dropping it.
  return [
    ...contested.map((entry) => ({
      root: entry.root,
      label: entry.label,
      color: entry.color,
      group: grouped ? entry.groupLabel : undefined,
    })),
    ...loose.map((entry) => ({
      root: entry.root,
      label: entry.label,
      color: entry.color,
      // Never headed, however many groups there are: a heading over the
      // packages no contest claimed would have no name to carry.
      group: undefined,
    })),
  ];
}

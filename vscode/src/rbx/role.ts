/**
 * The roles `problem.rbx.yml` hands out, and how the Explorer marks them.
 *
 * A role badge is deliberately a *different kind* of mark from an expectation
 * badge: two letters rather than a symbol, and one neutral hue rather than the
 * verdict palette. A generator makes no promise about how it will do -- there
 * is no judgement to colour -- so borrowing green or red for it would spend the
 * one channel that means "this passed or failed" on something that can do
 * neither.
 */

export type Role =
  | 'solution'
  | 'checker'
  | 'interactor'
  | 'validator'
  | 'visualizer'
  | 'generator'
  | 'statement';

/**
 * Which role wins when one file is claimed by two.
 *
 * Lower is more specific. A package that uses its checker as a validator too
 * should read as the checker: that is the role with the narrower meaning, and
 * the one the setter is more likely to be looking for. Solutions outrank
 * everything because theirs is the only badge carrying a declaration.
 */
const PRECEDENCE: readonly Role[] = [
  'solution',
  'checker',
  'interactor',
  'validator',
  'visualizer',
  'generator',
  'statement',
];

const BADGE: Record<Role, string> = {
  solution: '', // Solutions are badged with their expectation, never with this.
  checker: 'Ck',
  interactor: 'It',
  validator: 'Vl',
  visualizer: 'Vz',
  generator: 'Gn',
  statement: 'St',
};

const LABEL: Record<Role, string> = {
  solution: 'solution',
  checker: 'checker',
  interactor: 'interactor',
  validator: 'validator',
  visualizer: 'visualizer',
  generator: 'generator',
  statement: 'statement',
};

export function roleBadge(role: Role): string {
  return BADGE[role];
}

export function roleLabel(role: Role): string {
  return LABEL[role];
}

/** The more specific of two roles for the same file. */
export function moreSpecific(a: Role, b: Role): Role {
  return PRECEDENCE.indexOf(a) <= PRECEDENCE.indexOf(b) ? a : b;
}

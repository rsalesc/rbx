/**
 * Starting an ad-hoc run (`rbx irun`) from the editor (#907).
 *
 * Three ways in, one command line: a testcase the run or the testset already
 * has (`-t <group>/<index>`), a generator call (`-g "<call>"`), or text the
 * setter typed into a buffer (`--input <file>`, with `--answer <file>` when
 * they also typed the expected answer). Pure, so what gets typed into the
 * terminal is tested rather than trusted; irunCommands.ts asks the questions.
 */
import type { DeclaredAsset } from './manifest';
import type { TestcaseEntry } from './model';

/** What an ad-hoc run runs on. */
export type IrunTarget =
  | { readonly kind: 'test'; readonly selector: string }
  | { readonly kind: 'generator'; readonly call: string }
  | { readonly kind: 'input'; readonly input: string; readonly answer?: string };

/** How the solutions' output is judged. */
export type IrunCheck = 'answer' | 'none';

/**
 * The argv after `irun`.
 *
 * Solutions first, the way a setter types it. An empty list names none, and
 * `rbx irun` then runs every solution -- never its interactive picker, which
 * only `-c` asks for, so nothing here can leave a prompt in the terminal.
 */
export function irunArgs(
  target: IrunTarget,
  solutions: readonly string[],
  check: IrunCheck = 'answer',
): string[] {
  const args = [...solutions];
  switch (target.kind) {
    case 'test':
      args.push('-t', target.selector);
      break;
    case 'generator':
      args.push('-g', target.call);
      break;
    case 'input':
      args.push('--input', target.input);
      if (target.answer !== undefined && check === 'answer') {
        args.push('--answer', target.answer);
      }
      break;
  }
  if (check === 'none') {
    args.push('--no-check');
  }
  return args;
}

/**
 * The `-t` selector naming a testcase, or undefined when it has none.
 *
 * `<group>/<index>` with the index inside the top-level group, which is what
 * `TestcaseEntry.parse` reads. The one entry without a name is an ad-hoc run's
 * own typed input, filed under the synthetic `interactive` group: there is no
 * testcase called that to run again.
 */
export function testSelector(entry: TestcaseEntry): string | undefined {
  if (entry.group === 'interactive') {
    return undefined;
  }
  return `${entry.group}/${entry.index}`;
}

/** Whether a manifest declares an interactive (communication) problem. */
export function isCommunication(raw: unknown): boolean {
  return (
    typeof raw === 'object' &&
    raw !== null &&
    (raw as { type?: unknown }).type === 'communication'
  );
}

/** One row of the solution picker. */
export interface SolutionChoice {
  readonly path: string;
  /** The declared outcome, for the description; absent when none was. */
  readonly expectation?: string;
  readonly picked: boolean;
}

/**
 * The solutions a picker offers, in manifest order, and which start ticked.
 *
 * The ones `preselect` names when it names any that exist -- the row's own
 * solution, say. Otherwise the accepted ones: every solution is too many in a
 * package that keeps a slow solution for each verdict, and none would make
 * Enter run nothing.
 */
export function solutionChoices(
  assets: readonly DeclaredAsset[],
  preselect: readonly string[] = [],
): SolutionChoice[] {
  const solutions = assets.filter((asset) => asset.role === 'solution');
  const wanted = new Set(preselect.map(normalize));
  const anyWanted = solutions.some((asset) => wanted.has(normalize(asset.path)));
  return solutions.map((asset) => ({
    path: asset.path,
    ...(asset.expectation === undefined ? {} : { expectation: asset.expectation }),
    picked: anyWanted
      ? wanted.has(normalize(asset.path))
      : asset.expectation === 'ACCEPTED',
  }));
}

/** Forward slashes and no `./`, so a path from a run and one from a manifest compare. */
function normalize(solutionPath: string): string {
  return solutionPath.replace(/\\/g, '/').replace(/^\.\//, '');
}

/**
 * A generator call out of whatever line the cursor is on.
 *
 * A testplan or generator script line, as rbx's own grammar reads it: the
 * comment (`//` or `#`) and surrounding blanks go, and a line that is a
 * directive (`@copy`, `@input`, `@testgroup`, `}`) is not a call at all. A
 * trailing `@allow-duplicate` annotates the test, not the call, so it goes too.
 */
export function generatorCallFrom(line: string): string | undefined {
  const call = line
    .replace(/\/\/.*$/, '')
    .replace(/#.*$/, '')
    .trim()
    .replace(/\s+@allow-duplicate$/, '');
  if (call === '' || call.startsWith('@') || call.startsWith('}') || call.startsWith('{')) {
    return undefined;
  }
  return call;
}

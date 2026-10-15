/**
 * How a dispatched argument is quoted for the terminal's shell.
 *
 * Pure and free of Node imports, unlike its user dispatch.ts: the stress
 * launcher's webview shows the command it will run, and that preview has to
 * quote exactly what the terminal will be sent.
 */

/**
 * What a shell may see unquoted: no space, quote, glob, or operator -- and no
 * `,` or `@` at all, nor a leading `=`, `_`, `:`, `+` or `%`, which some shell
 * reads as syntax: zsh's `=cmd` expansion, PowerShell's `@x` splatting and
 * `a,b` array operator.
 */
const SHELL_SAFE = /^[A-Za-z0-9\-./][A-Za-z0-9_\-./=:+%]*$/;

/**
 * Whether an argument has to be quoted for the terminal's shell.
 *
 * VS Code's own quoting of a plain argument only reacts to spaces, takes an
 * argument already wrapped in quotes as pre-quoted, and never escapes a quote
 * inside -- fine for a solution path, not for a finder like `[a] ~ WA && [b]`
 * or a generator call like `gen [1..9] @`. Those go strongly (single-)quoted
 * instead; an argument holding a single quote cannot be, which is why
 * stressSpec.ts refuses one before it gets here.
 *
 * Known limitation: under Windows cmd.exe, VS Code's strong quoting is a pair
 * of double quotes, so a finder that quotes a path (`["a b.cpp"] ~ WA`) does
 * not survive it. Every other shell VS Code runs single-quotes.
 */
export function needsShellQuoting(arg: string): boolean {
  return !SHELL_SAFE.test(arg);
}

/**
 * One argument as a line shown or copied for a POSIX shell: single-quoted
 * unless plainly safe. A dispatch refuses a single quote before anything
 * runs (`singleQuoteProblem`), but a line is shown and copied before that,
 * so one is escaped (`'\''`) rather than left to end the quoting early.
 */
export function shellQuote(arg: string): string {
  return needsShellQuoting(arg) ? `'${arg.replace(/'/g, "'\\''")}'` : arg;
}

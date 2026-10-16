/**
 * Manifest globs (`solutions/good/*.*`, `validators/common-*.*`) as regexes
 * over absolute paths, so a file rbx expanded from one can be traced back to
 * the entry that declared it -- and so pick up what that entry declares
 * beyond its role (a solution's `outcomePerGroup`, its `score`).
 *
 * rbx expands these with `pathlib.Path.glob`: `*` and `?` stay within one
 * path segment, and `**` crosses any number of them.
 *
 * Pure: no `vscode` import.
 */

/** Whether a declared path is a glob rather than a single file. */
export function isGlob(declared: string): boolean {
  return /[*?[]/.test(declared);
}

/** A regex matching exactly the absolute paths `pattern` (absolute) expands to. */
export function globPattern(pattern: string): RegExp {
  let out = '';
  for (let i = 0; i < pattern.length; i++) {
    const c = pattern[i];
    if (c === '*') {
      if (pattern[i + 1] === '*') {
        // `**/` matches zero or more whole segments; a bare `**` anything.
        if (pattern[i + 2] === '/') {
          out += '(?:.*/)?';
          i += 2;
        } else {
          out += '.*';
          i += 1;
        }
      } else {
        out += '[^/]*';
      }
    } else if (c === '?') {
      out += '[^/]';
    } else if (c === '[') {
      const close = pattern.indexOf(']', i + 1);
      if (close < 0) {
        out += '\\[';
      } else {
        const body = pattern.slice(i + 1, close).replace(/^!/, '^').replace(/\\/g, '\\\\');
        out += `[${body}]`;
        i = close;
      }
    } else {
      out += c.replace(/[.+^${}()|\\]/g, '\\$&');
    }
  }
  return new RegExp(`^${out}$`);
}

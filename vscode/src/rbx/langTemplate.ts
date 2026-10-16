/**
 * The files a `{lang}` path template stands for.
 *
 * A wildcard statement (`language: '*'`) declares `file:
 * statement-{lang}.rbx.tex`, and rbx substitutes each language of the
 * package's effective `languages:` list into it. That list may come from the
 * problem or from its contest -- often through an `!include` -- so rather than
 * re-derive it, the template is matched against the files on disk: every file
 * the template fits, with one consistent value for every `{lang}` in it, is a
 * statement of that package. Kept as a template, the path names no file at all,
 * and nothing keyed on declared paths (the preview button, build on save, the
 * Explorer badge) ever sees the real one.
 */
import * as path from 'path';

export const LANG_PLACEHOLDER = '{lang}';

/** Lists a directory's entries, or returns `[]` for one that cannot be read. */
export type ReadDir = (dir: string) => Promise<string[]>;

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** A segment with `{lang}` in it as a pattern capturing the language. */
function segmentPattern(segment: string): RegExp {
  const parts = segment.split(LANG_PLACEHOLDER).map(escapeRegExp);
  return new RegExp(`^${parts.join('([^/\\\\]+)')}$`);
}

/**
 * A pattern matching every path `template` (absolute) could expand to, with
 * one language throughout -- or `undefined` for a template without `{lang}`.
 *
 * What a watcher asks of a created or deleted file: whether it is one more (or
 * one fewer) statement the template stands for.
 */
export function langTemplatePattern(template: string): RegExp | undefined {
  if (!template.includes(LANG_PLACEHOLDER)) {
    return undefined;
  }
  const [first, ...rest] = template.split(LANG_PLACEHOLDER).map(escapeRegExp);
  // The first `{lang}` captures; every later one must repeat it.
  const body = rest.map((part, i) => (i === 0 ? `([^/\\\\]+)${part}` : `\\1${part}`)).join('');
  return new RegExp(`^${first}${body}$`);
}

/**
 * Every existing path `template` (absolute) expands to, in no particular order.
 *
 * A template without `{lang}` is returned as is, whether or not it exists: a
 * declared file that is missing is still declared.
 */
export async function expandLangTemplate(template: string, readdir: ReadDir): Promise<string[]> {
  if (!template.includes(LANG_PLACEHOLDER)) {
    return [template];
  }
  const { root } = path.parse(template);
  const segments = template.slice(root.length).split(path.sep).filter((s) => s !== '');

  // Walk one segment at a time, carrying the language bound so far.
  let partial: { dir: string; lang?: string }[] = [{ dir: root }];
  for (const segment of segments) {
    const next: typeof partial = [];
    if (!segment.includes(LANG_PLACEHOLDER)) {
      for (const { dir, lang } of partial) {
        next.push({ dir: path.join(dir, segment), lang });
      }
    } else {
      const pattern = segmentPattern(segment);
      for (const { dir, lang } of partial) {
        for (const entry of await readdir(dir)) {
          const match = pattern.exec(entry);
          if (match === null) {
            continue;
          }
          const captured = match.slice(1);
          const bound = lang ?? captured[0];
          if (captured.every((value) => value === bound)) {
            next.push({ dir: path.join(dir, entry), lang: bound });
          }
        }
      }
    }
    partial = next;
  }
  return partial.map(({ dir }) => dir);
}

/**
 * What a click on a row does, as a pure function of the row and the click count.
 *
 * Split out of main.ts for the reason stated there: main.ts reads DOM events
 * and nothing else, so the one question a click asks -- open, expand, or
 * neither -- is answered here where `node --test` can hold it to account.
 *
 * No `vscode` import and no DOM, like render.ts and for the same reason.
 */
import type { Row } from '../rbx/viewModel';

export interface RowClick {
  /**
   * What the click does to the row's expansion.
   *
   * `expand` rather than a second `toggle` on the second click of a double
   * click: the first click may have *collapsed* the row, and a gesture that
   * opens a file should not also shut the thing it opened from. A double click
   * therefore always leaves the row expanded, whichever way it started.
   */
  readonly expansion: 'toggle' | 'expand' | 'none';
  /** Run the row's `primaryCommand`. */
  readonly invoke: boolean;
}

const NOTHING: RowClick = { expansion: 'none', invoke: false };

/**
 * `detail` is the browser's click count: 1 for a single click, 2 for the second
 * click of a double click. Both arrive, in that order, so a gesture is decided
 * across two calls and neither may repeat the other's work -- opening a
 * testcase twice, or expanding a node and instantly collapsing it again.
 */
export function rowClick(row: Row | undefined, detail: number): RowClick {
  if (row === undefined) {
    return NOTHING;
  }
  const opens = row.primaryCommand !== undefined;
  if (detail <= 1) {
    // A parent expands on a click anywhere along it, not just on the 16px
    // twisty; a leaf opens on a single click, as it did when this view was a
    // `TreeView` and the row carried `TreeItem.command`.
    return { expansion: row.expandable ? 'toggle' : 'none', invoke: !row.expandable && opens };
  }
  if (detail === 2 && row.expandable && opens) {
    // The only gesture that reaches a row which both expands and opens.
    return { expansion: 'expand', invoke: true };
  }
  return NOTHING;
}

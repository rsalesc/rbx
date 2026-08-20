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
   * Flip the row's expansion.
   *
   * On the second click of a double click this *undoes* what the first click
   * did, so a double click leaves the tree where it was and means only "open"
   * -- the same net effect a double click has on a folder in the Explorer.
   */
  readonly toggle: boolean;
  /** Run the row's `primaryCommand`. */
  readonly open: boolean;
}

const NOTHING: RowClick = { toggle: false, open: false };

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
    return { toggle: row.expandable, open: !row.expandable && opens };
  }
  if (detail === 2 && row.expandable && opens) {
    // The only gesture that reaches a row which both expands and opens: the
    // first click expanded it, so this one takes that back and opens instead.
    return { toggle: true, open: true };
  }
  return NOTHING;
}

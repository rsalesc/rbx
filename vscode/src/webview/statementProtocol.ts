/**
 * The messages between the statement preview panel and its webview client.
 *
 * Shared by both ends, so a renamed field fails to compile instead of silently
 * reading as absent. The host decides everything; the client renders the model
 * it is handed and reports clicks.
 */

/** One entry in the output picker. */
export interface OutputItem {
  readonly id: string;
  readonly label: string;
  readonly ok: boolean;
}

/** A finding as the banner lists it; `index` is what a click sends back. */
export interface FindingItem {
  readonly index: number;
  /** `file:line`, relative to the root where it can be. Absent when unlocated. */
  readonly where?: string;
  readonly message: string;
}

/** What the panel shows, minus the document itself. */
export interface PreviewModel {
  readonly outputs: readonly OutputItem[];
  readonly selected?: string;
  /** The selected output's last build, in words: `built 12:03 · 1.4s`. */
  readonly summary?: string;
  readonly ok: boolean;
  readonly findings: readonly FindingItem[];
  readonly building: boolean;
  readonly hasLog: boolean;
  readonly hasSource: boolean;
  /**
   * Why there is no document to show, when there is none: nothing built yet,
   * or an output the panel cannot render (Markdown, TeX).
   */
  readonly empty?: { readonly message: string; readonly action?: 'build' | 'open' };
}

export type HostMessage =
  | { readonly type: 'model'; readonly model: PreviewModel }
  /**
   * A PDF to show. `revision` changes whenever the file does; the same `id`
   * with a new revision is a rebuild, and keeps the reader's place.
   */
  | {
      readonly type: 'document';
      readonly id: string;
      readonly revision: string;
      readonly data: Uint8Array;
    };

export type ClientMessage =
  | { readonly type: 'ready' }
  | { readonly type: 'select'; readonly id: string }
  | { readonly type: 'build' }
  | { readonly type: 'openSource' }
  | { readonly type: 'openLog' }
  | { readonly type: 'openOutput' }
  | { readonly type: 'reveal'; readonly index: number };

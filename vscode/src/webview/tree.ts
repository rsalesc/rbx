/**
 * The tree behaviour both webview clients need, and neither should own.
 *
 * `main.ts` grew all of this while it was the only client: a roving-tabindex
 * `role="tree"`, an expansion set that remembers which nodes the *user* touched,
 * `getState`/`setState` persistence, scroll restoration, and a filter box whose
 * caret has to survive a re-render. None of it knows what a row means -- it
 * asks the client for the rows and for what a click on one does -- so copying
 * two hundred lines of keyboard handling into a second client is how the two
 * views would start navigating differently.
 *
 * What deliberately stayed behind in main.ts is everything that *does* know
 * about a run: mismatch cycling, the Compilation Findings panel and its
 * signature seeding, the channel keys. Bending this module around them would
 * make it a shared file with a run-shaped hole in it.
 *
 * DOM, no `vscode` module: like main.ts, this runs in a webview and talks to
 * the host only through the API the client acquired.
 */

/** The least a row has to be for this module to navigate it. */
export interface TreeRow {
  readonly id: string;
  readonly parentId?: string;
  readonly depth: number;
  readonly expandable: boolean;
  readonly defaultExpanded: boolean;
}

/**
 * What a click does, decided by the client.
 *
 * Passed in rather than computed here because the answer is about the row: the
 * run view's `gesture.rowClick` reads a `Row`, and this module is deliberately
 * blind to anything past `TreeRow`.
 */
export interface TreeClick {
  readonly expansion: 'toggle' | 'expand' | 'none';
  readonly invoke: boolean;
}

/** What the client persisted last time the view was alive. */
export interface TreeMemory {
  readonly expanded?: readonly string[];
  readonly touched?: readonly string[];
  readonly selected?: string;
}

export interface TreeOptions<R extends TreeRow> {
  /** The `role="tree"` element, part of the static shell so focus survives. */
  readonly container: HTMLElement;
  /** The rows on screen, in order -- filtering and collapse already applied. */
  visible(): readonly R[];
  rowById(id: string | undefined): R | undefined;
  /** Redraw whatever the client draws from its state. */
  render(): void;
  /** Run the row's primary command. */
  invoke(row: R | undefined): void;
  click(row: R | undefined, detail: number): TreeClick;
  /** Ask the client to persist; it decides what its blob holds. */
  save(): void;
  readonly memory?: TreeMemory;
}

export class TreeController<R extends TreeRow> {
  /** Ids the user, or the `defaultExpanded` seed, has opened. */
  private expandedIds: Set<string>;
  /**
   * Ids the user has opened or closed by hand.
   *
   * Without this, a re-render cannot tell "never seen" from "deliberately
   * closed", and the `defaultExpanded` seed would reopen every node the user
   * shut. The TreeView got that distinction free from `TreeItem.id`
   * persistence; losing it would be a regression.
   */
  private readonly touched: Set<string>;
  private selectedId?: string;

  constructor(private readonly options: TreeOptions<R>) {
    this.expandedIds = new Set(options.memory?.expanded ?? []);
    this.touched = new Set(options.memory?.touched ?? []);
    this.selectedId = options.memory?.selected;
    options.container.addEventListener('click', (event) => this.onClick(event));
    options.container.addEventListener('keydown', (event) => this.onKeyDown(event));
    options.container.addEventListener('scroll', () => options.save());
  }

  get expanded(): ReadonlySet<string> {
    return this.expandedIds;
  }

  get selected(): string | undefined {
    return this.selectedId;
  }

  /** What the client folds into its persisted blob. */
  snapshot(): { expanded: string[]; touched: string[]; selected?: string; scrollTop: number } {
    return {
      expanded: [...this.expandedIds],
      touched: [...this.touched],
      selected: this.selectedId,
      scrollTop: this.options.container.scrollTop,
    };
  }

  select(id: string | undefined): void {
    this.selectedId = id;
    this.options.render();
    this.focusSelected();
    this.options.save();
  }

  toggle(id: string, open?: boolean): void {
    const shouldOpen = open ?? !this.expandedIds.has(id);
    if (shouldOpen) {
      this.expandedIds.add(id);
    } else {
      this.expandedIds.delete(id);
    }
    // Remember that this one was the user's call, so the next model's
    // `defaultExpanded` seed leaves it alone.
    this.touched.add(id);
    this.options.render();
    this.focusSelected();
    this.options.save();
  }

  /**
   * Open what the model says opens by default, without undoing the user.
   *
   * `extraIds` are ids that expand through the same set but are not tree rows
   * -- the run view's finding rows -- and are named here only so the prune
   * below does not throw them away.
   */
  seed(rows: readonly R[], extraIds: readonly string[] = []): void {
    const ids = new Set([...rows.map((row) => row.id), ...extraIds]);
    for (const row of rows) {
      if (row.defaultExpanded && !this.touched.has(row.id)) {
        this.expandedIds.add(row.id);
      }
    }
    // Rows that no longer exist would otherwise accumulate forever across runs.
    // `touched` is pruned with `expanded` and for the same reason: it is only
    // ever read for rows of the current model, and the persisted blob is
    // rewritten on every scroll.
    this.expandedIds = new Set([...this.expandedIds].filter((id) => ids.has(id)));
    for (const id of [...this.touched]) {
      if (!ids.has(id)) {
        this.touched.delete(id);
      }
    }
    if (this.selectedId !== undefined && !ids.has(this.selectedId)) {
      this.selectedId = undefined;
    }
  }

  /** Open every ancestor of `id`, so a jump can land on a buried row. */
  reveal(id: string): void {
    let row = this.options.rowById(id);
    while (row?.parentId !== undefined) {
      this.expandedIds.add(row.parentId);
      row = this.options.rowById(row.parentId);
    }
  }

  elementFor(id: string | undefined): HTMLElement | null {
    if (id === undefined) {
      return null;
    }
    return this.options.container.querySelector(`[data-id="${CSS.escape(id)}"]`);
  }

  focusSelected(): void {
    const element = this.elementFor(this.selectedId);
    if (element === null) {
      return;
    }
    element.focus({ preventScroll: true });
    element.scrollIntoView({ block: 'nearest' });
  }

  /** Whether the focus is inside the tree, asked *before* a re-render. */
  holdsFocus(): boolean {
    return this.options.container.contains(document.activeElement);
  }

  /**
   * Put the focus back after a re-render replaced the element holding it.
   *
   * Without this a keyboard or screen-reader user is dropped out to `<body>` on
   * every tick of a run. When the focused row went away with the refresh, the
   * container keeps the focus inside the view so the next arrow key still
   * reaches the tree.
   */
  restoreFocus(): void {
    if (this.elementFor(this.selectedId) === null) {
      this.options.container.focus({ preventScroll: true });
    } else {
      this.focusSelected();
    }
  }

  get scrollTop(): number {
    return this.options.container.scrollTop;
  }

  set scrollTop(value: number) {
    this.options.container.scrollTop = value;
  }

  private onClick(event: MouseEvent): void {
    const target = event.target as HTMLElement;
    const element = target.closest('.row') as HTMLElement | null;
    const id = element?.dataset.id;
    if (id === undefined) {
      return;
    }
    const row = this.options.rowById(id);
    const action = this.options.click(row, event.detail);
    if (action.expansion === 'none') {
      this.select(id);
    } else {
      // Assigned rather than passed through `select`, which renders: `toggle`
      // renders too, and doing both would draw the view twice per click.
      this.selectedId = id;
      this.toggle(id, action.expansion === 'expand' ? true : undefined);
    }
    if (action.invoke) {
      this.options.invoke(row);
    }
  }

  private onKeyDown(event: KeyboardEvent): void {
    const rows = this.options.visible();
    const at = rows.findIndex((row) => row.id === this.selectedId);
    const row = at < 0 ? undefined : rows[at];
    const move = (index: number): void => {
      const target = rows[Math.max(0, Math.min(rows.length - 1, index))];
      if (target !== undefined) {
        this.select(target.id);
      }
    };

    switch (event.key) {
      case 'ArrowDown':
        move(at + 1);
        break;
      case 'ArrowUp':
        move(at < 0 ? 0 : at - 1);
        break;
      case 'ArrowRight':
        if (row === undefined) {
          return;
        }
        if (row.expandable && !this.expandedIds.has(row.id)) {
          this.toggle(row.id, true);
        } else {
          move(at + 1);
        }
        break;
      case 'ArrowLeft':
        if (row === undefined) {
          return;
        }
        if (row.expandable && this.expandedIds.has(row.id)) {
          this.toggle(row.id, false);
        } else if (row.parentId !== undefined) {
          this.select(row.parentId);
        }
        break;
      case 'Home':
        move(0);
        break;
      case 'End':
        move(rows.length - 1);
        break;
      case 'Enter':
        this.options.invoke(row);
        break;
      default:
        return;
    }
    event.preventDefault();
  }
}

export interface FilterBoxOptions {
  /** The element the box is drawn into; replaced wholesale on every render. */
  readonly host: HTMLElement;
  /** The markup, which the client's renderer produces from its own state. */
  html(): string;
  onInput(value: string): void;
  /** Escape on a non-empty filter. The client clears its state and re-renders. */
  onClear(): void;
  /** The filter as the client currently holds it, so Escape knows whether to act. */
  value(): string;
}

/**
 * The filter box: its markup, its two shortcuts, and its caret.
 *
 * The caret and not just the focus. The host re-posts the model on every
 * file-watcher tick, and putting the caret back at the end would move it out
 * from under someone editing the middle of a filter.
 */
export class FilterBox {
  constructor(private readonly options: FilterBoxOptions) {
    options.host.addEventListener('input', (event) => {
      options.onInput((event.target as HTMLInputElement).value);
    });
    document.addEventListener('keydown', (event) => this.onKeyDown(event));
  }

  input(): HTMLInputElement | null {
    return document.getElementById('filter') as HTMLInputElement | null;
  }

  /**
   * Redraw the box, keeping the caret if it was in it.
   *
   * Returns whether the focus was restored, which is how the client knows not
   * to hand it back to the tree instead.
   */
  render(): boolean {
    const input = this.input();
    const focused = input !== null && document.activeElement === input;
    const start = focused ? input.selectionStart : null;
    const end = focused ? input.selectionEnd : null;
    this.options.host.innerHTML = this.options.html();
    if (!focused) {
      return false;
    }
    const next = this.input();
    next?.focus();
    if (start !== null && end !== null) {
      next?.setSelectionRange(start, end);
    }
    return true;
  }

  private onKeyDown(event: KeyboardEvent): void {
    const input = this.input();
    if (event.key === '/' && document.activeElement !== input) {
      input?.focus();
      input?.select();
      event.preventDefault();
      return;
    }
    if (event.key === 'Escape' && this.options.value() !== '') {
      this.options.onClear();
      event.preventDefault();
    }
  }
}

/**
 * The problem dropdown's host, redrawn only when it would actually differ.
 *
 * A `<select>` is the one control in the view that cannot survive being
 * rebuilt: replacing the element drops the focus and, on some platforms, snaps
 * the open list shut. The host re-posts the whole model on every file-watcher
 * tick, so without this guard a run would fight anyone trying to use the
 * dropdown -- and during a run the problems and the selection are exactly what
 * does *not* change, so comparing the markup skips almost every tick.
 */
export class SelectorHost {
  private html = '';

  constructor(private readonly host: HTMLElement) {}

  render(next: string): void {
    if (next === this.html) {
      return;
    }
    const select = this.select();
    const focused = select !== null && document.activeElement === select;
    this.html = next;
    this.host.innerHTML = next;
    if (focused) {
      this.select()?.focus();
    }
  }

  private select(): HTMLSelectElement | null {
    return document.getElementById('problem') as HTMLSelectElement | null;
  }
}

/**
 * Coalesce writes to `setState`, which is called from scroll handlers.
 *
 * 100ms, the interval main.ts has always used: long enough that a flick of the
 * scroll wheel writes once, short enough that a view hidden immediately after a
 * change still persisted it.
 */
export function debounce(run: () => void, ms = 100): () => void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return () => {
    if (timer !== undefined) {
      clearTimeout(timer);
    }
    timer = setTimeout(run, ms);
  };
}

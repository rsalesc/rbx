/**
 * The time-profile editor's call queue: at most one rbx call in flight, and
 * the latest wanted edit always wins.
 *
 * An edit asked for while another runs does not wait in line behind it -- it
 * *replaces* whatever was waiting, because the client always sends an absolute
 * value (the limit it wants, never "+100"). So any number of clicks or drag
 * steps costs at most one call beyond the one running. A refresh (re-reading
 * the buffer, say after a save) is coalesced the same way and always yields to
 * a waiting edit, since the edit's answer carries everything a refresh would.
 *
 * `updating` is the only state the UI reads, and it is derived, never set: it
 * is true exactly while an edit runs or waits. There is no flag for a failed
 * or superseded call to forget to clear -- which is how the editor's buttons
 * used to end up disabled for good when a refresh overtook an edit.
 */
export interface EditQueueHooks<E> {
  runEdit(edit: E): Promise<void>;
  refresh(): Promise<void>;
  /** After every call, failed or not: the moment to redraw. */
  settled(): void | Promise<void>;
  onError?(error: unknown): void;
}

export class EditQueue<E> {
  private wanted?: E;
  private refreshWanted = false;
  private inFlight = false;
  private editing = false;
  private draining?: { promise: Promise<void>; resolve: () => void };

  constructor(private readonly hooks: EditQueueHooks<E>) {}

  /** An edit runs or waits: what the screen shows may be a step ahead of rbx. */
  get updating(): boolean {
    return this.editing || this.wanted !== undefined;
  }

  edit(edit: E): void {
    this.wanted = edit;
    void this.pump();
  }

  refresh(): void {
    this.refreshWanted = true;
    void this.pump();
  }

  /** Resolves once nothing runs or waits. For tests, and for disposal. */
  idle(): Promise<void> {
    if (!this.inFlight && this.wanted === undefined && !this.refreshWanted) {
      return Promise.resolve();
    }
    if (this.draining === undefined) {
      let resolve!: () => void;
      const promise = new Promise<void>((r) => (resolve = r));
      this.draining = { promise, resolve };
    }
    return this.draining.promise;
  }

  private async pump(): Promise<void> {
    if (this.inFlight) return;
    const wanted = this.wanted;
    if (wanted === undefined && !this.refreshWanted) {
      this.draining?.resolve();
      this.draining = undefined;
      return;
    }
    this.inFlight = true;
    try {
      if (wanted !== undefined) {
        this.wanted = undefined;
        this.editing = true;
        await this.hooks.runEdit(wanted);
      } else {
        this.refreshWanted = false;
        await this.hooks.refresh();
      }
    } catch (error) {
      this.hooks.onError?.(error);
    } finally {
      this.inFlight = false;
      this.editing = false;
    }
    try {
      await this.hooks.settled();
    } catch (error) {
      this.hooks.onError?.(error);
    }
    void this.pump();
  }
}

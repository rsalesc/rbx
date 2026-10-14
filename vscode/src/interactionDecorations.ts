/**
 * Who said what, drawn over the `io` channel's transcript.
 *
 * The transcript document holds payload only (`artifactFs` renders it), so
 * that copying a line copies data. Everything a `<` or `>` used to say is put
 * back here as decoration, which the editor draws and never copies:
 *
 *   - an arrow before each line -- `→` the interactor speaking to the
 *     solution, `←` the solution answering, `!` its stderr;
 *   - a whole-line tint per side, so a long turn reads as one block;
 *   - `#n` after the first line of each solution turn, which for most
 *     protocols is the query count;
 *   - a footer after the last line: the verdict, the turn count, who spoke
 *     last and the interactor's own last word from `.int.err`.
 *
 * A real editor rather than a webview for the reason `testcasePanes.ts` gives:
 * transcripts run to 10^5 lines, and find, go-to-line, selection and the
 * scrollbar all come with a `TextDocument` for free. Each turn is also a fold
 * region, so a long answer collapses to its first line.
 *
 * See `docs/plans/2026-10-14-vscode-interaction-channel-design.md`.
 */
import * as fs from 'fs/promises';
import * as vscode from 'vscode';

import { SCHEME, realPathOf } from './artifactFs';
import {
  InteractionDocument,
  Pipe,
  footerText,
  interactionDocument,
  transcriptSiblings,
} from './rbx/interaction';
import { parseEvaluation } from './rbx/model';
import { LABELS, isInteractionLabel } from './rbx/panes';
import { readYamlFile } from './rbx/store';

const SELECTOR: vscode.DocumentSelector = {
  scheme: SCHEME,
  pattern: `**/${LABELS.interaction}`,
};

/** What a transcript document is decorated with, worked out once per open. */
interface Loaded {
  readonly document: InteractionDocument;
  /** Absent for a raw fallback, which has no turns to sum up. */
  readonly footer?: string;
}

function isTranscript(document: vscode.TextDocument): boolean {
  return document.uri.scheme === SCHEME && isInteractionLabel(document.uri.path);
}

async function readText(filePath: string): Promise<string | undefined> {
  try {
    return await fs.readFile(filePath, 'utf8');
  } catch {
    return undefined;
  }
}

/**
 * Parse the transcript again from disk, plus the siblings its footer reads.
 *
 * Again rather than out of the document: the document holds payload only, and
 * who wrote each line is exactly what it no longer says. Parsing goes through
 * the same `interactionDocument` that rendered it, so the two cannot disagree
 * about which line is which.
 */
async function load(uri: vscode.Uri): Promise<Loaded | undefined> {
  const realPath = realPathOf(uri);
  const raw = await readText(realPath);
  if (raw === undefined) {
    return undefined;
  }
  const document = interactionDocument(raw, realPath);
  if (document.kind === 'raw') {
    return { document };
  }
  const siblings = transcriptSiblings(realPath);
  const evaluation =
    siblings === undefined ? undefined : parseEvaluation(await readYamlFile(siblings.evalPath));
  const interactorStderr =
    siblings === undefined ? undefined : await readText(siblings.interactorStderrPath);
  return {
    document,
    footer: footerText(document.rendered, { outcome: evaluation?.outcome, interactorStderr }),
  };
}

function lineType(pipe: Pipe): vscode.TextEditorDecorationType {
  const arrow: Record<Pipe, string> = { interactor: '→', solution: '←', stderr: '!' };
  const color: Record<Pipe, string> = {
    interactor: 'rbx.interaction.interactorForeground',
    solution: 'rbx.interaction.solutionForeground',
    stderr: 'rbx.interaction.stderrForeground',
  };
  const background: Record<Pipe, string> = {
    interactor: 'rbx.interaction.interactorBackground',
    solution: 'rbx.interaction.solutionBackground',
    stderr: 'rbx.interaction.stderrBackground',
  };
  return vscode.window.createTextEditorDecorationType({
    isWholeLine: true,
    backgroundColor: new vscode.ThemeColor(background[pipe]),
    before: {
      contentText: arrow[pipe],
      color: new vscode.ThemeColor(color[pipe]),
      // A fixed-width gutter of its own, so the payload of every line starts
      // in the same column whatever the arrow is.
      width: '2ch',
      fontWeight: 'bold',
    },
  });
}

class InteractionDecorator implements vscode.Disposable {
  private readonly lines: Record<Pipe, vscode.TextEditorDecorationType> = {
    interactor: lineType('interactor'),
    solution: lineType('solution'),
    stderr: lineType('stderr'),
  };
  private readonly counter = vscode.window.createTextEditorDecorationType({
    after: {
      color: new vscode.ThemeColor('editorLineNumber.foreground'),
      margin: '0 0 0 2ch',
    },
  });
  private readonly footer = vscode.window.createTextEditorDecorationType({
    after: {
      color: new vscode.ThemeColor('editorCodeLens.foreground'),
      fontStyle: 'italic',
      margin: '0 0 0 4ch',
    },
  });
  private readonly banner = vscode.window.createTextEditorDecorationType({
    isWholeLine: true,
    color: new vscode.ThemeColor('errorForeground'),
  });

  /**
   * One load per document, shared by the decorations and the folding ranges.
   * Keyed on the URI string, whose query is the real path: a transcript never
   * changes underneath an open document (artifacts are replaced, not
   * rewritten -- see `artifactFs`), so nothing here goes stale while open.
   */
  private readonly cache = new Map<string, Promise<Loaded | undefined>>();

  loaded(uri: vscode.Uri): Promise<Loaded | undefined> {
    const key = uri.toString();
    let entry = this.cache.get(key);
    if (entry === undefined) {
      entry = load(uri);
      this.cache.set(key, entry);
    }
    return entry;
  }

  forget(document: vscode.TextDocument): void {
    this.cache.delete(document.uri.toString());
  }

  async decorate(editor: vscode.TextEditor): Promise<void> {
    if (!isTranscript(editor.document)) {
      return;
    }
    const loaded = await this.loaded(editor.document.uri);
    if (loaded === undefined) {
      return;
    }
    if (loaded.document.kind === 'raw') {
      editor.setDecorations(this.banner, [new vscode.Range(0, 0, 0, 0)]);
      return;
    }
    const { rendered } = loaded.document;
    const byPipe: Record<Pipe, vscode.Range[]> = { interactor: [], solution: [], stderr: [] };
    rendered.pipes.forEach((pipe, line) => {
      byPipe[pipe].push(new vscode.Range(line, 0, line, 0));
    });
    for (const pipe of Object.keys(byPipe) as Pipe[]) {
      editor.setDecorations(this.lines[pipe], byPipe[pipe]);
    }

    editor.setDecorations(
      this.counter,
      rendered.turns
        .filter((turn) => turn.pipe === 'solution')
        .map((turn) => ({
          range: lineEnd(editor.document, turn.start),
          renderOptions: { after: { contentText: `#${turn.ordinal}` } },
        })),
    );

    const last = Math.max(0, editor.document.lineCount - 1);
    editor.setDecorations(
      this.footer,
      loaded.footer === undefined
        ? []
        : [
            {
              range: lineEnd(editor.document, last),
              renderOptions: { after: { contentText: `── ${loaded.footer}` } },
            },
          ],
    );
  }

  dispose(): void {
    for (const type of [
      ...Object.values(this.lines),
      this.counter,
      this.footer,
      this.banner,
    ]) {
      type.dispose();
    }
    this.cache.clear();
  }
}

function lineEnd(document: vscode.TextDocument, line: number): vscode.Range {
  const end = document.lineAt(line).range.end;
  return new vscode.Range(end, end);
}

class TurnFoldingProvider implements vscode.FoldingRangeProvider {
  constructor(private readonly decorator: InteractionDecorator) {}

  async provideFoldingRanges(document: vscode.TextDocument): Promise<vscode.FoldingRange[]> {
    const loaded = await this.decorator.loaded(document.uri);
    if (loaded === undefined || loaded.document.kind === 'raw') {
      return [];
    }
    return loaded.document.rendered.turns
      .filter((turn) => turn.end > turn.start)
      .map((turn) => new vscode.FoldingRange(turn.start, turn.end));
  }
}

export function registerInteractionDecorations(context: vscode.ExtensionContext): void {
  const decorator = new InteractionDecorator();
  const decorateVisible = (editors: readonly vscode.TextEditor[]): void => {
    for (const editor of editors) {
      void decorator.decorate(editor);
    }
  };
  context.subscriptions.push(
    decorator,
    vscode.window.onDidChangeVisibleTextEditors(decorateVisible),
    vscode.workspace.onDidCloseTextDocument((document) => decorator.forget(document)),
    vscode.languages.registerFoldingRangeProvider(SELECTOR, new TurnFoldingProvider(decorator)),
  );
  decorateVisible(vscode.window.visibleTextEditors);
}

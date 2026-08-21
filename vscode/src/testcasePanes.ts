/**
 * The two editor panes a testcase opens into, and the channel one of them holds.
 *
 * Real editors rather than a webview, and the reason is size: testcases are
 * routinely megabytes, and a webview would have to ship its own virtual
 * scroller before it could display one -- then reimplement find, go-to-line and
 * word wrap on top of it. A `TextDocument` gets all of that, and the diff
 * editor's change navigation, for free.
 *
 * Two properties of editor groups are load-bearing here:
 *
 *   - **A preview tab is per group.** With each pane in its own group, arrowing
 *     down the testcase list *replaces* the documents in place and accumulates
 *     no tabs -- `rbx ui`'s live-follow behaviour, from a mechanism a webview
 *     does not have.
 *   - **The user can rearrange them**, which is a requirement rather than a
 *     bonus, and is what makes `findPane` below the centre of this file.
 *
 * See `docs/plans/2026-08-21-vscode-testcase-detail-design.md`.
 */
import * as vscode from 'vscode';

import { SCHEME, artifactUri, firstExisting } from './artifactFs';
import { TestcaseNode } from './rbx/nodes';
import {
  Artifact,
  Channel,
  DiffArtifact,
  PaneKind,
  asTestcaseLayout,
  channelArtifact,
  inputArtifact,
  isDiff,
  labelPrefix,
  layoutCommand,
  paneKindOf,
} from './rbx/panes';

/**
 * Every `rbx:` URI a tab is showing.
 *
 * A diff contributes both of its sides, because either one identifies the group
 * as the channel pane: the output and the answer are only ever opened together
 * and only ever there.
 */
function artifactUris(tab: vscode.Tab): vscode.Uri[] {
  const input = tab.input;
  if (input instanceof vscode.TabInputText) {
    return [input.uri];
  }
  if (input instanceof vscode.TabInputTextDiff) {
    return [input.original, input.modified];
  }
  return [];
}

/**
 * Which group one of our panes is currently in, if it is open at all.
 *
 * This is what keeps a dragged pane where it was put. `setEditorLayout`
 * rearranges the *whole* editor area -- the solution source being edited
 * included -- so calling it on every open would undo the user's arrangement on
 * every arrow key. Finding the pane instead means the layout is a seed used
 * once and then never again.
 *
 * Recognition goes through the `rbx:` scheme and the URI's display path, which
 * `artifactFs` builds and whose last segment is the tab's title. Nothing else
 * in the window can produce one, so a match is never a false positive.
 */
function findPane(kind: PaneKind): vscode.ViewColumn | undefined {
  for (const group of vscode.window.tabGroups.all) {
    for (const tab of group.tabs) {
      for (const uri of artifactUris(tab)) {
        if (uri.scheme === SCHEME && paneKindOf(uri.path) === kind) {
          return group.viewColumn;
        }
      }
    }
  }
  return undefined;
}

export class TestcasePanes {
  /**
   * Which channel the second pane is on, remembered across testcases.
   *
   * Sticky on purpose: reading stderr and arrowing down a group should keep
   * reading stderr, exactly as `rbx ui`'s switcher does. A channel that reset
   * per testcase would make the switch useless for the one thing it is for --
   * comparing the same channel across several tests.
   */
  private channel: Channel = 'out';

  /**
   * The testcase the panes are showing.
   *
   * Kept so `alt+2` has something to act on: a channel switch names no row, and
   * without this it would have nothing to re-open.
   */
  private current?: TestcaseNode;

  /**
   * Open both panes on `node`, seeding the layout only if they are not already
   * on screen.
   */
  async open(node: TestcaseNode, channel?: Channel): Promise<void> {
    this.current = node;
    if (channel !== undefined) {
      this.channel = channel;
    }
    let inputColumn = findPane('input');
    let channelColumn = findPane('channel');
    if (inputColumn === undefined && channelColumn === undefined) {
      // Neither pane exists: first open of the session, or the user closed
      // both. This is the only branch that can touch the layout at all.
      //
      // And it only does so when there is nothing to destroy. Laying out is
      // global: it would collapse a three-group arrangement someone built for
      // themselves down to two, which is precisely the thing this class exists
      // to avoid doing. So the seed is offered to an editor area that has no
      // arrangement yet, and an area that has one is joined rather than
      // rearranged.
      if (vscode.window.tabGroups.all.length <= 1) {
        await this.seedLayout();
        inputColumn = vscode.ViewColumn.One;
        channelColumn = vscode.ViewColumn.Two;
      } else {
        inputColumn = vscode.window.tabGroups.activeTabGroup.viewColumn;
        channelColumn = vscode.ViewColumn.Beside;
      }
    }
    // One pane open and not the other -- the user closed one -- puts the
    // missing one beside its surviving sibling rather than re-imposing a
    // layout over an arrangement they are evidently still using.
    await this.showArtifact(
      inputArtifact(node.testcase),
      labelPrefix(node.run.solution.path, node.group.name, node.testcase.stem),
      inputColumn ?? vscode.ViewColumn.Beside,
    );
    await this.showChannel(node, channelColumn ?? vscode.ViewColumn.Beside);
  }

  /**
   * Switch the channel pane, on whichever testcase is already open.
   *
   * `node` is set when the switch came from a card button, which names the row
   * it sits under; it is absent for the keyboard, which names nothing and acts
   * on what the panes are already showing.
   */
  async setChannel(channel: Channel, node?: TestcaseNode): Promise<void> {
    const target = node ?? this.current;
    if (target === undefined) {
      // Nothing is open and nothing was named. Silent rather than a warning:
      // the keybinding is live whenever the view has focus, and scolding
      // someone for pressing it before opening a testcase teaches nothing.
      return;
    }
    // Through `open` rather than `showChannel` alone: a button pressed on a row
    // whose panes were never opened should open them, and one pressed on a
    // *different* row should move both panes to it, not leave the input behind
    // showing another testcase.
    await this.open(target, channel);
  }

  private async seedLayout(): Promise<void> {
    const layout = asTestcaseLayout(
      vscode.workspace.getConfiguration('rbx').get('testcaseLayout'),
    );
    await vscode.commands.executeCommand(layoutCommand(layout));
  }

  private async showChannel(node: TestcaseNode, column: vscode.ViewColumn): Promise<void> {
    const artifact = channelArtifact(this.channel, node.testcase);
    const prefix = labelPrefix(node.run.solution.path, node.group.name, node.testcase.stem);
    if (!isDiff(artifact)) {
      await this.showArtifact(artifact, prefix, column);
      return;
    }
    await this.showDiff(artifact, prefix, column, node);
  }

  private async showDiff(
    artifact: DiffArtifact,
    prefix: string,
    column: vscode.ViewColumn,
    node: TestcaseNode,
  ): Promise<void> {
    const output = await firstExisting(artifact.left.paths);
    const answer = await firstExisting(artifact.right.paths);
    if (output === undefined || answer === undefined) {
      // A hard TLE or an RTE never produced a complete output, and a package
      // built without answers has no right-hand side. Showing whichever half
      // exists beats an empty diff -- the same fallback `rbx.diffOutput` has
      // always made.
      const half = output === undefined ? artifact.right : artifact.left;
      await this.showArtifact(half, prefix, column);
      return;
    }
    await vscode.commands.executeCommand(
      'vscode.diff',
      artifactUri(output, `${prefix}/${artifact.left.label}`),
      artifactUri(answer, `${prefix}/${artifact.right.label}`),
      `${node.run.solution.path} · ${node.group.name}/${node.testcase.stem}`,
      // `preserveFocus` so the focus stays in the sidebar and the next arrow key
      // still moves the selection -- which is the whole point of panes that
      // follow it. `preview` so the tab is reused rather than piled up.
      { viewColumn: column, preview: true, preserveFocus: true },
    );
  }

  private async showArtifact(
    artifact: Artifact,
    prefix: string,
    column: vscode.ViewColumn,
  ): Promise<void> {
    const realPath = await firstExisting(artifact.paths);
    if (realPath === undefined) {
      // Said rather than drawn. A dimmed button would report the same absence
      // with less information and, because availability changes from testcase
      // to testcase, would reflow the button row while arrowing through a group.
      vscode.window.showInformationMessage(artifact.missing);
      return;
    }
    const uri = artifactUri(realPath, `${prefix}/${artifact.label}`);
    const document = await vscode.workspace.openTextDocument(uri);
    await vscode.window.showTextDocument(document, {
      viewColumn: column,
      preview: true,
      preserveFocus: true,
    });
  }
}

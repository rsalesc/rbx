/**
 * The "rbx" output channel.
 *
 * The extension reads files it did not write, in a layout that varies with the
 * installed rbx version, so "the view is empty" has several possible causes:
 * no package found, no run yet, or a skeleton we could not parse. The log says
 * which, without needing a debugger attached.
 */
import * as vscode from 'vscode';

let channel: vscode.OutputChannel | undefined;

export function initLog(context: vscode.ExtensionContext): void {
  channel = vscode.window.createOutputChannel('rbx');
  context.subscriptions.push(channel);
}

export function log(message: string): void {
  channel?.appendLine(message);
}

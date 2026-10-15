/**
 * The Stress view's markup, as pure functions of its model.
 *
 * Three sections rendered apart -- declared stresses, the status line, the
 * findings -- because the status is rewritten about once a second while a
 * session runs, and redrawing the findings with it would take keyboard focus
 * off whichever row button held it.
 *
 * Every button carries `data-action` and whatever it acts on (`data-name`,
 * `data-k`); stressMain.ts reads those and nothing else, so what a button does
 * is decided here, next to the button.
 */
import type {
  StressChip,
  StressDeclaredRow,
  StressFindingRow,
  StressStatus,
  StressViewModel,
} from '../rbx/stressViewModel';
import { escapeAttr, escapeHtml } from './render';

function codicon(name: string): string {
  return `<span class="codicon codicon-${name}" aria-hidden="true"></span>`;
}

function iconButton(
  action: string,
  icon: string,
  title: string,
  data: Record<string, string | number>,
): string {
  const attrs = Object.entries(data)
    .map(([key, value]) => ` data-${key}="${escapeAttr(String(value))}"`)
    .join('');
  return (
    `<button class="stress-icon-button" data-action="${action}"${attrs} ` +
    `title="${escapeAttr(title)}" aria-label="${escapeAttr(title)}">${codicon(icon)}</button>`
  );
}

/** `m:ss`, the way a stopwatch reads; a budget is never long enough for hours. */
export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

/**
 * The elapsed clock, against the budget when there is one.
 *
 * `now` is only consulted for a running session: its manifest's `elapsed` is
 * up to a second old by design, and the start time ticks smoothly. An ended
 * session's `elapsed` is final and is shown as written.
 */
export function renderElapsed(status: StressStatus, now: number): string {
  const elapsed =
    status.startedAtMs === undefined
      ? status.elapsed
      : Math.max(status.elapsed, (now - status.startedAtMs) / 1000);
  const shown =
    status.timeout === undefined ? elapsed : Math.min(elapsed, status.timeout);
  return status.timeout === undefined
    ? formatClock(shown)
    : `${formatClock(shown)} / ${formatClock(status.timeout)}`;
}

function declaredRow(row: StressDeclaredRow, dispatch: boolean): string {
  const actions = dispatch
    ? iconButton('run-declared', 'play', `Run ${row.name}`, { name: row.name }) +
      iconButton('edit-declared', 'edit', `Edit ${row.name} in the launcher`, { name: row.name })
    : '';
  return (
    '<li class="stress-row">' +
    `<span class="stress-row-text"><span class="stress-name">${escapeHtml(row.name)}</span>` +
    `<span class="stress-summary" title="${escapeAttr(row.summary)}">${escapeHtml(row.summary)}</span></span>` +
    `<span class="stress-actions">${actions}</span>` +
    '</li>'
  );
}

export function renderDeclared(model: StressViewModel): string {
  if (model.noPackage) {
    return (
      '<div class="welcome"><p>No rbx problem selected.</p>' +
      '<p>Open a folder with a <code>problem.rbx.yml</code> to stress test it.</p></div>'
    );
  }
  const rows = model.declared.map((row) => declaredRow(row, model.dispatch)).join('');
  const create = model.dispatch
    ? '<li class="stress-row"><button class="stress-link" data-action="new">' +
      `${codicon('add')} New stress…</button></li>`
    : '';
  return (
    '<h3 class="stress-heading">Stresses</h3>' +
    `<ul class="stress-list" aria-label="Declared stresses">${rows}${create}</ul>`
  );
}

export function renderStatus(model: StressViewModel, now: number): string {
  const status = model.status;
  if (model.noPackage || status === undefined) {
    return '';
  }
  const stop =
    model.dispatch && status.state === 'running'
      ? iconButton('stop', 'debug-stop', 'Stop the stress test', {})
      : '';
  const findings =
    status.findingsLimit === undefined
      ? `${status.findings}`
      : `${status.findings}/${status.findingsLimit}`;
  const counts = [
    `${status.executed} run`,
    ...(status.skipped > 0 ? [`${status.skipped} skipped`] : []),
    `${findings} found`,
  ].join(' · ');
  return (
    '<div class="stress-status">' +
    '<div class="stress-status-line">' +
    `<span class="stress-state hue-${status.hue}">${escapeHtml(status.label)}</span>` +
    `<span class="stress-elapsed">${escapeHtml(renderElapsed(status, now))}</span>` +
    `<span class="stress-actions">${stop}</span>` +
    '</div>' +
    `<div class="stress-counts">${escapeHtml(counts)}</div>` +
    `<div class="stress-spec" title="${escapeAttr(status.spec)}"><code>${escapeHtml(status.spec)}</code></div>` +
    '</div>'
  );
}

function chip(item: StressChip): string {
  const title = `${item.path}: ${item.short}`;
  return (
    `<span class="stress-chip hue-${item.hue}" title="${escapeAttr(title)}">` +
    `${codicon(item.icon)}${escapeHtml(item.solution)} ${escapeHtml(item.short)}</span>`
  );
}

function findingRow(row: StressFindingRow): string {
  const k = { k: row.k };
  const actions =
    iconButton('open', 'go-to-file', `Open finding #${row.k}`, k) +
    (row.canCompare ? iconButton('compare', 'diff', `Compare outputs of finding #${row.k}`, k) : '') +
    iconButton('copy', 'copy', `Copy the generator call of finding #${row.k}`, k) +
    iconButton('promote', 'arrow-up', `Promote finding #${row.k} into the testset`, k);
  const promoted =
    row.promoted === undefined
      ? ''
      : `<span class="stress-promoted">in ${escapeHtml(row.promoted)}</span>`;
  const duration =
    row.duration === undefined ? '' : `<span class="stress-duration">${escapeHtml(row.duration)}</span>`;
  return (
    `<li class="stress-finding" data-k="${row.k}">` +
    '<div class="stress-finding-head">' +
    `<span class="stress-index">#${row.k}</span>` +
    `<code class="stress-call" title="${escapeAttr(row.call)}">${escapeHtml(row.call)}</code>` +
    duration +
    `<span class="stress-actions">${actions}</span>` +
    '</div>' +
    `<div class="stress-chips">${row.chips.map(chip).join('')}${promoted}</div>` +
    '</li>'
  );
}

export function renderFindings(model: StressViewModel): string {
  if (model.noPackage) {
    return '';
  }
  if (model.status === undefined) {
    return '<div class="welcome"><p>Run a stress to see findings here.</p></div>';
  }
  if (model.findings.length === 0) {
    return (
      '<div class="welcome"><p>' +
      (model.status.state === 'running' ? 'No findings yet.' : 'No findings in this session.') +
      '</p></div>'
    );
  }
  return (
    '<h3 class="stress-heading">Findings</h3>' +
    `<ul class="stress-list" aria-label="Findings">${model.findings.map(findingRow).join('')}</ul>`
  );
}

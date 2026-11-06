/**
 * The time-profile editor's document, as HTML, from what `rbx time-inspect`
 * printed. Pure: no DOM, no `vscode`, so it is testable under `node --test`.
 *
 * Interactive elements carry `data-action` (and `data-row`/`data-path`); the
 * client (limitsMain.ts) turns them into messages to the host. Nothing here
 * decides whether a limit is good -- the statuses are rbx's.
 */
import type {
  GroupCheck,
  InspectResult,
  Row,
  SolutionCheck,
} from '../rbx/limitsInspect';
import { expectationDisplay } from '../rbx/expectation';

export function esc(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return '—';
  }
  return value >= 10_000 ? `${(value / 1000).toFixed(1)} s` : `${value} ms`;
}

function basename(path: string): string {
  return path.split('/').pop() ?? path;
}

/** The margins the estimate was built with, as the hovers spell them out. */
interface Margins {
  readonly ac?: number;
  readonly toTle?: number;
}

function isAccepted(s: SolutionCheck): boolean {
  return s.role.toUpperCase() === 'LOWER';
}

/**
 * rbx's status, worded for what actually happens at this limit.
 *
 * `passes` is rbx's name for "finishes within TL × timeLimitToTle", which is
 * not the same as being accepted: a solution finishing between TL and that
 * multiple still gets TLE, just with less margin than asked for. The two read
 * very differently to a setter, so they are told apart here by the one number
 * the status does not carry -- whether the time is under the limit itself.
 */
function statusWording(s: SolutionCheck, tl: number | null, m: Margins): { label: string; hint: string } {
  const k = m.toTle;
  switch (s.status) {
    case 'ok':
      return isAccepted(s)
        ? {
            label: 'ok',
            hint: `Accepted at ${ms(s.time)}${s.min_ms !== null ? `; needs TL ≥ ${ms(s.min_ms)}${m.ac !== undefined ? ` (×${m.ac} headroom)` : ''}, and has it.` : '.'}`,
          }
        : {
            label: 'ok',
            hint:
              s.time !== null
                ? `Still running past TL × ${k ?? '?'}${tl !== null && k !== undefined ? ` = ${ms(Math.round(tl * k))}` : ''} (finishes at ${ms(s.time)}): times out with margin.`
                : `Seen still running at ${ms(s.survived_at)}, past TL × ${k ?? '?'}: times out with margin.`,
          };
    case 'thin':
      return {
        label: 'thin headroom',
        hint: `Accepted at ${ms(s.time)}, but under the ×${m.ac ?? '?'} headroom acToTimeLimit asks for: needs TL ≥ ${ms(s.min_ms)}.`,
      };
    case 'fails':
      return { label: 'would get TLE', hint: `Should be accepted, but takes ${ms(s.time)}: longer than the limit.` };
    case 'passes':
      if (s.time !== null && tl !== null && s.time <= tl) {
        return { label: 'would be accepted', hint: `Should be too slow, but finishes at ${ms(s.time)}: within the limit itself.` };
      }
      return {
        label: `margin < ×${k ?? '?'}`,
        hint: `Still gets TLE, but finishes at ${ms(s.time)}, before TL × ${k ?? '?'}${tl !== null && k !== undefined ? ` = ${ms(Math.round(tl * k))}` : ''}: less margin than timeLimitToTle asks for.${s.max_ms !== null ? ` Keep TL ≤ ${ms(s.max_ms)} to restore it.` : ''}`,
      };
    case 'unverified':
      return {
        label: 'unverified',
        hint: `Only seen still running at ${ms(s.survived_at)}; TL × ${k ?? '?'} is now higher, so nothing measured says it still times out with margin.${s.max_ms !== null ? ` Verified for TL ≤ ${ms(s.max_ms)}.` : ''}`,
      };
    case 'unchecked':
      return {
        label: 'unchecked',
        hint: k === undefined ? 'No timeLimitToTle is set, so nothing checks slow solutions.' : 'Never run during the estimate.',
      };
  }
}

function statusChip(s: SolutionCheck, tl: number | null, m: Margins): string {
  const { label, hint } = statusWording(s, tl, m);
  return `<span class="status st-${s.status}" title="${esc(hint)}">${esc(label)}</span>`;
}

// ---------------------------------------------------------------- the strip

interface Domain {
  readonly lo: number;
  readonly hi: number;
}

const STRIP_W = 1000;
const STRIP_H = 64;
const PAD_X = 16;
const AXIS_Y = 40;

function domainFor(rows: Row[], toTle: number | undefined): Domain {
  const values: number[] = [];
  for (const row of rows) {
    if (row.timeLimit !== null) {
      values.push(row.timeLimit, row.timeLimit * (toTle ?? 1));
    }
    if (row.check?.min_ms) values.push(row.check.min_ms);
    if (row.check?.max_ms) values.push(row.check.max_ms);
    for (const s of row.solutions) {
      if (s.time) values.push(s.time);
      if (s.survived_at) values.push(s.survived_at);
    }
  }
  const positive = values.filter((v) => v > 0);
  if (positive.length === 0) {
    return { lo: 1, hi: 10_000 };
  }
  return { lo: Math.max(1, Math.min(...positive) / 1.6), hi: Math.max(...positive) * 1.6 };
}

function xOf(value: number, d: Domain): number {
  const t = (Math.log10(Math.max(value, d.lo)) - Math.log10(d.lo)) / (Math.log10(d.hi) - Math.log10(d.lo));
  return PAD_X + Math.min(1, Math.max(0, t)) * (STRIP_W - 2 * PAD_X);
}

function ticks(d: Domain): number[] {
  const out: number[] = [];
  for (let p = Math.floor(Math.log10(d.lo)); p <= Math.ceil(Math.log10(d.hi)); p++) {
    for (const m of [1, 2, 5]) {
      const v = m * 10 ** p;
      if (v >= d.lo && v <= d.hi) out.push(v);
    }
  }
  return out;
}

function tickLabel(v: number): string {
  return v >= 1000 ? `${v / 1000}s` : `${v}ms`;
}

function strip(row: Row, d: Domain, m: Margins): string {
  const toTle = m.toTle;
  const parts: string[] = [];
  const check = row.check;
  // The range of limits the evidence allows: the green band.
  if (check && (check.min_ms !== null || check.max_ms !== null)) {
    const a = xOf(check.min_ms ?? d.lo, d);
    const b = xOf(check.max_ms ?? d.hi, d);
    if (b > a) {
      parts.push(
        `<rect class="band" x="${a}" y="${AXIS_Y - 14}" width="${b - a}" height="28" rx="3"><title>Limits the evidence allows: ${esc(ms(check.min_ms))} … ${esc(check.max_ms === null ? '∞' : ms(check.max_ms))}</title></rect>`,
      );
    }
  }
  parts.push(`<line class="axis" x1="${PAD_X}" y1="${AXIS_Y}" x2="${STRIP_W - PAD_X}" y2="${AXIS_Y}"/>`);
  for (const t of ticks(d)) {
    const x = xOf(t, d);
    parts.push(`<line class="tick" x1="${x}" y1="${AXIS_Y + 14}" x2="${x}" y2="${AXIS_Y + 18}"/>`);
    parts.push(`<text class="ticklabel" x="${x}" y="${AXIS_Y + 22}">${tickLabel(t)}</text>`);
  }
  if (row.timeLimit !== null) {
    const x = xOf(row.timeLimit, d);
    parts.push(
      `<line class="tl" x1="${x}" y1="${AXIS_Y - 22}" x2="${x}" y2="${AXIS_Y + 14}"/><text class="tllabel" x="${x}" y="${AXIS_Y - 25}">TL ${esc(ms(row.timeLimit))}</text>`,
    );
    if (toTle !== undefined) {
      const xt = xOf(row.timeLimit * toTle, d);
      parts.push(
        `<line class="tle" x1="${xt}" y1="${AXIS_Y - 16}" x2="${xt}" y2="${AXIS_Y + 14}"><title>TL × timeLimitToTle (${toTle}) = ${esc(ms(Math.round(row.timeLimit * toTle)))}: a slow solution must still be running here</title></line><text class="tlelabel" x="${xt}" y="${AXIS_Y - 19}">×${toTle}</text>`,
      );
    }
  }
  for (const s of row.solutions) {
    const label = `${s.path} (${s.language}) — ${isAccepted(s) ? 'accepted' : 'too slow'}, ${
      s.time !== null ? ms(s.time) : s.survived_at !== null ? `still running at ${ms(s.survived_at)}` : 'never measured'
    } — ${statusWording(s, row.timeLimit, m).label}`;
    if (isAccepted(s) && s.time !== null) {
      const x = xOf(s.time, d);
      parts.push(
        `<circle class="pt st-${s.status}" data-action="open" data-path="${esc(s.path)}" cx="${x}" cy="${AXIS_Y}" r="6"><title>${esc(label)}</title></circle>`,
      );
    } else if (!isAccepted(s) && s.time !== null) {
      const x = xOf(s.time, d);
      parts.push(
        `<g class="pt st-${s.status}" data-action="open" data-path="${esc(s.path)}"><title>${esc(label)}</title><path d="M${x - 6},${AXIS_Y - 6} L${x + 6},${AXIS_Y + 6} M${x + 6},${AXIS_Y - 6} L${x - 6},${AXIS_Y + 6}" /></g>`,
      );
    } else if (!isAccepted(s) && s.survived_at !== null) {
      const x = xOf(s.survived_at, d);
      parts.push(
        `<g class="pt st-${s.status}" data-action="open" data-path="${esc(s.path)}"><title>${esc(label)}</title><path class="fill" d="M${x - 6},${AXIS_Y - 7} L${x + 6},${AXIS_Y} L${x - 6},${AXIS_Y + 7} Z" /><text class="survived" x="${x + 9}" y="${AXIS_Y + 4}">≥</text></g>`,
      );
    }
  }
  return `<svg class="strip" viewBox="0 0 ${STRIP_W} ${STRIP_H}" preserveAspectRatio="xMidYMid meet" role="img">${parts.join('')}</svg>`;
}

// ---------------------------------------------------------------- the table

function solutionLink(s: SolutionCheck): string {
  const display = expectationDisplay(s.expectedOutcome ?? undefined);
  const hue = display ? ` hue-${display.hue}` : '';
  const title = display ? `${s.path} — expected ${display.label}` : s.path;
  return `<a href="#" class="sol${hue}${display?.bold ? ' bold' : ''}" data-action="open" data-path="${esc(s.path)}" title="${esc(title)}">${esc(basename(s.path))}</a>`;
}

function solutionTable(solutions: SolutionCheck[], tl: number | null, m: Margins): string {
  if (solutions.length === 0) {
    return '';
  }
  const body = solutions
    .map((s) => {
      const accepted = isAccepted(s);
      const time =
        s.time !== null
          ? ms(s.time)
          : s.survived_at !== null
            ? `<span title="Never finished; still running at this limit">≥ ${esc(ms(s.survived_at))}</span>`
            : '<span class="dim">not run</span>';
      const allows = accepted
        ? s.min_ms !== null
          ? `TL ≥ ${esc(ms(s.min_ms))}`
          : '—'
        : s.max_ms !== null
          ? `TL ≤ ${esc(ms(s.max_ms))}`
          : '—';
      return `<tr>
        <td>${solutionLink(s)}</td>
        <td>${esc(s.language)}</td>
        <td><span class="role ${accepted ? 'ac' : 'tle'}" title="${accepted ? 'Bounds the limit from below: must be accepted' : 'Bounds the limit from above: must time out'}">${accepted ? 'AC' : 'TLE'}</span></td>
        <td class="num">${time}</td>
        <td class="num">${allows}</td>
        <td>${statusChip(s, tl, m)}</td>
      </tr>`;
    })
    .join('');
  return `<table class="sols">
    <colgroup><col class="c-sol"><col class="c-lang"><col class="c-role"><col class="c-num"><col class="c-num"><col class="c-status"></colgroup>
    <thead><tr><th>solution</th><th>lang</th><th>role</th><th class="num">time</th><th class="num">allows</th><th>status</th></tr></thead>
    <tbody>${body}</tbody></table>`;
}

// ---------------------------------------------------------------- rows

function badge(kind: 'ok' | 'warn' | 'err', text: string, hint: string): string {
  return `<span class="badge ${kind}" title="${esc(hint)}">${esc(text)}</span>`;
}

function checkBadges(check: GroupCheck | null, m: Margins): string {
  if (check === null) {
    return '';
  }
  const tl = check.time_limit;
  const k = m.toTle;
  const tleAt = k !== undefined ? Math.round(tl * k) : undefined;
  const out: string[] = [];

  // The fast side.
  if (check.rejectsOwnSolutions) {
    out.push(
      badge(
        'err',
        `${basename(check.min_solution ?? 'an accepted solution')} would get TLE`,
        `The slowest accepted solution takes ${ms(check.slowest_ms)}, longer than this ${ms(tl)} limit.`,
      ),
    );
  } else if (check.belowMin) {
    out.push(
      badge(
        'warn',
        `headroom < ×${m.ac ?? '?'}`,
        `Every accepted solution still passes, but the slowest (${check.min_solution ?? '?'}, ${ms(check.slowest_ms)}) gets less than the ×${m.ac ?? '?'} headroom acToTimeLimit asks for. Raise TL to ≥ ${ms(check.min_ms)}.`,
      ),
    );
  }

  // The slow side. A violating solution finishing *within* the limit really is
  // accepted; one finishing between TL and TL × timeLimitToTle still gets TLE,
  // only with less margin than asked for -- a warning, not a wrong verdict.
  for (const v of check.violating) {
    const name = basename(v.solution ?? '?');
    if (v.value <= tl) {
      out.push(
        badge('err', `${name} would be accepted`, `Should be too slow, but finishes at ${ms(v.value)}: within this ${ms(tl)} limit.`),
      );
    } else {
      out.push(
        badge(
          'warn',
          `${name}: TLE margin < ×${k ?? '?'}`,
          `Still gets TLE, but finishes at ${ms(v.value)}, before TL × ${k ?? '?'} = ${ms(tleAt)}: less margin than timeLimitToTle asks for.${check.max_ms !== null ? ` Keep TL ≤ ${ms(check.max_ms)} to restore it.` : ''}`,
        ),
      );
    }
  }
  if (check.violating.length === 0 && check.max_ms !== null && tl > check.max_ms) {
    // Above the bound without a measured finish to name: the bound came from a
    // solution only seen still running.
    out.push(
      badge(
        'warn',
        `TLE margin < ×${k ?? '?'}`,
        `${check.max_solution ?? 'A slow solution'} was only shown to run past TL × ${k ?? '?'} for TL ≤ ${ms(check.max_ms)}.`,
      ),
    );
  }
  if (check.unverified.length > 0) {
    out.push(
      badge(
        'warn',
        `${check.unverified.length} slow unverified`,
        `${check.unverified.join(', ')}: only seen still running at a lower limit than TL × ${k ?? '?'} = ${ms(tleAt)}, so nothing measured says ${check.unverified.length === 1 ? 'it' : 'they'} still time out with margin. Re-estimate to check.`,
      ),
    );
  }

  if (out.length === 0 && check.ok) {
    const lines: string[] = [];
    if (check.min_ms !== null) {
      lines.push(
        `Accepted: the slowest takes ${ms(check.slowest_ms)}; with ×${m.ac ?? '?'} headroom it needs TL ≥ ${ms(check.min_ms)}.`,
      );
    }
    if (check.max_ms !== null) {
      lines.push(`Too slow: ${check.max_solution ?? 'every slow solution'} keeps a ×${k ?? '?'} margin for TL ≤ ${ms(check.max_ms)}.`);
    }
    if (check.confirmed.length > 0) {
      lines.push(`Seen still running past TL × ${k ?? '?'} = ${ms(tleAt)}: ${check.confirmed.join(', ')}.`);
    }
    if (lines.length === 0) {
      lines.push('Nothing recorded for this group bounds the limit.');
    }
    out.push(badge('ok', `margins hold at ${ms(tl)}`, lines.join('\n')));
  }
  return out.join(' ');
}

function limitEditor(row: Row, step: number, disabled: boolean): string {
  const value = row.timeLimit ?? '';
  const dis = disabled ? ' disabled' : '';
  return `<span class="tl-editor">
    <button class="icon" data-action="step" data-row="${row.key}" data-delta="${-step}" title="−${step} ms"${dis}><i class="codicon codicon-remove"></i></button>
    <input type="number" min="1" step="${step}" value="${value}" data-action="set" data-row="${row.key}" aria-label="time limit in ms"${dis}/>
    <span class="unit">ms</span>
    <button class="icon" data-action="step" data-row="${row.key}" data-delta="${step}" title="+${step} ms"${dis}><i class="codicon codicon-add"></i></button>
  </span>`;
}

function handSet(row: Row, disabled: boolean): string {
  const estimated = row.check?.estimated;
  if (estimated === null || estimated === undefined) {
    return '';
  }
  return `<span class="handset" title="Set by hand; the evidence was measured at ${esc(ms(estimated))}">✎ estimated ${esc(ms(estimated))}
    <button class="link" data-action="revert" data-row="${row.key}"${disabled ? ' disabled' : ''}>revert</button></span>`;
}

function derivation(row: Row): string {
  const r = row.report;
  if (r === null) return '';
  if (r.origin === 'multiplier') {
    const parts = [`${r.multiplier ?? '?'}× ${esc(r.relativeToLanguage ?? '?')}`];
    if (r.increment) parts.push(`+ ${r.increment} ms`);
    return `<span class="derived" title="Derived from another group; re-estimate to change the rule">${parts.join(' ')} = ${esc(ms(row.timeLimit))}</span>`;
  }
  if (r.origin === 'defaulted') {
    return `<span class="derived" title="No solution measured this group">defaulted to ${esc(ms(row.timeLimit))}</span>`;
  }
  return '';
}

function groupSection(row: Row, d: Domain, m: Margins, step: number, busy: boolean, title: string): string {
  const r = row.report;
  const origin = r ? `<span class="origin o-${r.origin}">${esc(r.origin)}${r.isLeftover ? ' · leftover' : ''}</span>` : '';
  const editor = row.editable ? limitEditor(row, step, busy) : derivation(row) || `<b>${esc(ms(row.timeLimit))}</b>`;
  const measured =
    r && r.solutionCount
      ? `<span class="dim">${r.solutionCount} solution(s) · fastest ${esc(ms(r.fastest))} · slowest ${esc(ms(r.slowest))}</span>`
      : '';
  const hasStrip = row.solutions.length > 0 || row.check !== null;
  return `<section class="group">
    <div class="group-head">
      <span class="langs">${title}</span>
      ${editor}
      ${origin}
      ${handSet(row, busy)}
      <span class="badges">${checkBadges(row.check, m)}</span>
    </div>
    ${measured ? `<div class="measured">${measured}</div>` : ''}
    ${hasStrip ? strip(row, d, m) : ''}
    ${solutionTable(row.solutions, row.timeLimit, m)}
  </section>`;
}

// ---------------------------------------------------------------- document

export interface ViewState {
  readonly result?: InspectResult;
  readonly busy: boolean;
  /** The host's own failure: rbx missing, a crash, an unreadable answer. */
  readonly error?: string;
}

const STALE_TEXT: Record<string, string> = {
  solutions: 'Solutions changed since this profile was estimated.',
  interactor: 'The interactor changed since this profile was estimated.',
  tests: 'The tests changed since this profile was estimated.',
};

function multipliersLine(result: InspectResult): string {
  const m = result.multipliers;
  if (m) {
    const bits: string[] = [];
    if (m.acToTimeLimit !== undefined) bits.push(`slowest AC × ${m.acToTimeLimit}`);
    if (m.fastestToTimeLimit !== undefined) bits.push(`fastest AC × ${m.fastestToTimeLimit}`);
    if (m.timeLimitToTle !== undefined) bits.push(`slow must survive TL × ${m.timeLimitToTle}`);
    if (m.timeResolution !== undefined) bits.push(`rounded to ${m.timeResolution} ms`);
    return `<div class="rule"><span class="k">multipliers</span> ${bits.map(esc).join(' · ')}</div>`;
  }
  if (result.formula) {
    return `<div class="rule"><span class="k">formula</span> <code>${esc(result.formula)}</code></div>`;
  }
  return '';
}

function effectiveLine(result: InspectResult): string {
  const e = result.effective;
  if (!e) return '';
  const chips = e.languages
    .map((l) => `<span class="eff" title="${esc(`${l.memoryLimit} MB`)}"><b>${esc(l.language)}</b> ${esc(ms(l.timeLimit))}</span>`)
    .join('');
  return `<section class="effective">
    <h3>What a run is judged against</h3>
    <div class="effs">${chips}</div>
    <div class="dim">problem.rbx.yml: ${esc(ms(e.package.timeLimit))} · ${e.package.memoryLimit} MB · output ${e.package.outputLimit} KB</div>
  </section>`;
}

export function renderDocument(state: ViewState): string {
  if (state.error !== undefined) {
    return `<div class="fatal"><i class="codicon codicon-error"></i> ${esc(state.error)}
      <div><button data-action="openText">Open as text</button> <button data-action="refresh">Retry</button></div></div>`;
  }
  const result = state.result;
  if (result === undefined) {
    return `<div class="loading"><i class="codicon codicon-loading codicon-modifier-spin"></i> Asking rbx about this profile…</div>`;
  }
  if (result.errors.length > 0) {
    return `<div class="fatal"><i class="codicon codicon-warning"></i> rbx could not read this profile:
      <pre>${esc(result.errors.join('\n'))}</pre>
      <div><button data-action="openText">Open as text</button></div></div>`;
  }
  const busy = state.busy;
  const step = result.multipliers?.timeResolution ?? 100;
  const toTle = result.multipliers?.timeLimitToTle;
  const margins: Margins = { ac: result.multipliers?.acToTimeLimit, toTle };
  const rows = result.rows ?? [];
  const base = rows.find((r) => r.key === 'base');
  const groups = rows.filter((r) => r.key !== 'base');
  const d = domainFor(rows, toTle);

  const stale = result.stale
    ? `<div class="banner warn"><i class="codicon codicon-warning"></i> ${esc(STALE_TEXT[result.stale] ?? 'This profile is stale.')}
        <button data-action="reestimate">Re-estimate ${esc(result.profile)}</button></div>`
    : '';
  const inherit = result.inheritFromPackage
    ? `<div class="banner info"><i class="codicon codicon-info"></i> This profile uses the limits in problem.rbx.yml; the estimate below is kept but not applied.</div>`
    : '';
  const notEstimated = !result.editable && !result.inheritFromPackage
    ? `<div class="banner info"><i class="codicon codicon-info"></i> Not an estimated profile: there is nothing to check limits against.
        <button data-action="reestimate">Estimate ${esc(result.profile)}</button></div>`
    : '';

  const dis = busy ? ' disabled' : '';
  const baseEditor =
    base && base.editable
      ? limitEditor(base, step, busy)
      : `<input type="number" min="1" step="${step}" value="${result.timeLimit ?? ''}" data-action="set" data-row="base" placeholder="package" aria-label="base time limit"${dis}/> <span class="unit">ms</span>`;

  const header = `<header>
    <div class="title"><h2><i class="codicon codicon-watch"></i> ${esc(result.profile)}</h2>
      <span class="dim path">${esc(result.path)}</span>
      <span class="spacer"></span>
      ${busy ? '<i class="codicon codicon-loading codicon-modifier-spin" title="rbx is working"></i>' : ''}
      <button class="secondary" data-action="reestimate" title="rbx time -p ${esc(result.profile)}"><i class="codicon codicon-play"></i> Re-estimate</button>
      <button class="secondary" data-action="openText" title="Open the YAML"><i class="codicon codicon-go-to-file"></i> YAML</button>
    </div>
    ${stale}${inherit}${notEstimated}
    <div class="limits ${result.inheritFromPackage ? 'muted' : ''}">
      <label>Base TL ${baseEditor}</label>
      ${base ? handSet(base, busy) : ''}
      ${base ? `<span class="badges">${checkBadges(base.check, margins)}</span>` : ''}
      <label>ML <input type="number" min="1" value="${result.memoryLimit ?? ''}" placeholder="${result.effective?.package.memoryLimit ?? ''}" data-action="memory" aria-label="memory limit in MB"${dis}/> <span class="unit">MB</span></label>
      <label class="check"><input type="checkbox" data-action="inherit" ${result.inheritFromPackage ? 'checked' : ''}${dis}/> use problem.rbx.yml limits</label>
    </div>
    ${multipliersLine(result)}
  </header>`;

  const groupSections = groups
    .map((g) => groupSection(g, d, margins, step, busy, esc((g.report?.languages ?? []).join(', '))))
    .join('');
  const leftover =
    base && base.solutions.length > 0
      ? groupSection({ ...base, editable: false, check: null }, d, margins, step, busy, 'other languages (base limit)')
      : '';
  const onlyBase =
    groups.length === 0 && base && (base.solutions.length > 0 || base.check)
      ? groupSection(base, d, margins, step, busy, 'all languages')
      : '';
  const noSolutions = !result.hasSolutions && rows.some((r) => r.report)
    ? `<div class="banner info"><i class="codicon codicon-info"></i> This profile recorded no per-solution timings (older rbx); showing group summaries only.</div>`
    : '';

  const legend = `<div class="legend dim">
    <span><svg width="12" height="12"><circle cx="6" cy="6" r="5" class="pt st-ok"/></svg> accepted</span>
    <span><svg width="12" height="12"><path d="M1,1 L11,11 M11,1 L1,11" class="pt st-ok" style="stroke-width:2"/></svg> too slow, finished</span>
    <span><svg width="12" height="12"><path d="M1,0 L11,6 L1,12 Z" class="pt st-ok fill"/></svg> too slow, still running at</span>
    <span><span class="swatch band"></span> limits the evidence allows</span>
    <span><span class="swatch tl"></span> TL</span>
    <span><span class="swatch tle"></span> TL × timeLimitToTle</span>
  </div>`;

  return `${header}
    <main class="${result.inheritFromPackage ? 'muted' : ''}">
      ${noSolutions}
      ${groups.length > 0 || onlyBase ? `<h3>Groups</h3>${legend}` : ''}
      ${groupSections}${onlyBase}${leftover}
    </main>
    ${effectiveLine(result)}`;
}

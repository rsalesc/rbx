# VS Code: the interaction channel (#905)

## Problem

For a communication task, the files a setter most needs are on disk and the
extension does not show them: the interaction transcript (`<stem>.pio`), the
interactor's stderr and log (`.int.err`, `.int.log`) and the checker's stderr
(`.checker.err`). `rbx ui` shows the transcript in its `InteractionBox`; in VS
Code you dig through `.rbx/runs/` by hand.

## Decisions

Brainstormed against a dedicated webview (two-lane chat, sequence diagram,
aligned grid). Chosen: **a decorated read-only editor**, because transcripts
run to 10^5 lines and a `TextDocument` brings find, go-to-line, selection, the
scrollbar and folding for free -- the same argument `testcasePanes.ts` makes
for testcases.

1. **Placement: just another channel.** `alt+4` (`io`) swaps the second pane
   exactly like `out`/`err`/`log`. No layout changes. On a communication task
   it is the *default* channel: the sticky channel is remembered per kind of
   task (`StickyChannels`), starting at `io` for interactive problems and `out`
   for batch ones.
2. **Text model: payload only.** The document is `5 100`, `? 3`, not
   `<5 100`, `>? 3`, so a copied line is data. `artifactFs` renders it when the
   URI's label is `interaction.io`; the same `.pio` opened under any other
   label is served raw.
3. **Who said what is decoration.** Per line: an arrow in a fixed 2ch gutter
   (`→` interactor, `←` solution, `!` stderr) and a whole-line tint, both
   theme colours contributed by the extension (`rbx.interaction.*`). `#n`
   after the first line of each solution turn -- for most protocols, the
   query count. Each multi-line turn is a fold region.
4. **Verdict: inline footer + own channel.** After the last line, a
   decoration (never text): `✕ WA · 101 solution turns · interactor spoke
   last · int.err: <last line of .int.err>`. The full `.int.err` is `alt+5`.
5. **Turns.** Consecutive lines from one side are one turn; stderr neither
   breaks nor starts a turn.

## Channels

| key | channel | file | shown on card |
|---|---|---|---|
| alt+1 | `out` | output vs answer (diff) | always |
| alt+2 | `err` | `.err` / `.sol.err` | always |
| alt+3 | `log` | `.log` | always |
| alt+4 | `io` | `.pio`, rendered | communication |
| alt+5 | `ierr` | `.int.err` | communication |
| alt+6 | `ilog` | `.int.log` | communication |
| alt+7 | `cerr` | `.checker.err` | always (`chk`) |

"Communication" is read per testcase off `.eval`'s `result.interactor_timing`,
which rbx records for every run that had an interactor. A problem is
interactive or not, so the card's rows never reflow while arrowing.

Missing files say why, in words, as every channel already does. A missing
transcript says *Re-run with `rbx -cp run` to capture the interaction* unless
the skeleton says the run captured (`capture_pipes` or `merge_stderr`).

The card also shows `interactor N ms · checker N ms` from `.eval`.

`rbx.copyInteraction` (editor title on the transcript, and the testcase context
menu) copies the transcript back in `.interaction` form, ready to become a
statement sample.

## Failure states

- Unparseable file: the raw file under a one-line banner, decorated red -- the
  same fallback `rbx ui` makes.
- No `.pio`: the hint above.

## Code

- `vscode/src/rbx/interaction.ts` -- pure: parser (a port of
  `testcase_utils.parse_interaction`, plus blank-line tolerance), rendering,
  turns, footer, `.interaction` serialisation. Tested in
  `interaction.test.ts`, mirroring the Python parser's tests.
- `vscode/src/interactionDecorations.ts` -- decorations and folding ranges.
- `vscode/src/rbx/panes.ts` -- the four channels and their labels.
- `vscode/src/artifactFs.ts` -- renders `interaction.io`.

## Out of scope

- Per-message timing: the `.pio` has no timestamps.
- Comparing two solutions' transcripts side by side.
- Tests view parity (the `.interaction` of built samples, and the build's
  `.err`/`.log`): the Tests view's panes have no channels yet.
- Shortening very long lines: decorations cannot hide text, and the document
  must keep the full text for copying.

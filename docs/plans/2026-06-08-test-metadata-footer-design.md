# Docked testcase-metadata footer in run mode (issue #404)

## Problem

In the `rbx ui` run-mode test explorer (`RunTestExplorerScreen`), pressing `g`
opens a blocking modal (`RichLogModal`) showing the selected test's *generation*
metadata. While the modal is open the user cannot scroll the test list, so they
cannot browse tests while keeping the metadata in view.

The non-run `TestExplorerScreen` already solves this: it docks a `#test-metadata`
`RichLogBox` at the bottom of the details panel, toggled by `m`, and repopulates
it live as the selection changes. The app stylesheet (`app.tcss:89`) already
styles `#test-metadata` for **both** screens, even though run mode does not yet
mount that widget — the intended design is to give run mode the same footer.

## Goal

Replace the run-mode testcase-metadata modal with a docked, toggleable footer
mirroring `TestExplorerScreen`, and unify the metadata key so `m` means
"testcase metadata" in both screens.

## Resulting run-mode key map

| Key     | Before                                | After                                                          |
| ------- | ------------------------------------- | ------------------------------------------------------------- |
| `m`     | toggle run/eval metadata (per-side)   | **toggle testcase-generation metadata footer** (`#test-metadata`) |
| `r`     | — (free)                              | **toggle run/eval metadata** (per-side `#test-box-metadata`)  |
| `g`     | push testcase-metadata modal          | **removed**                                                   |
| others  | `1 2 3`, `s`, `v V`, `q`              | unchanged                                                     |

`TestExplorerScreen` is untouched (already `m` = testcase metadata). The footer
starts hidden; `m` toggles it and, once shown, it stays docked and repopulates
on every selection — matching the run-metadata box's behavior.

## Components changed

1. **`rbx/box/ui/screens/run_test_explorer.py`** (the bulk):
   - `compose()`: append `yield RichLogBox(id='test-metadata')` to the
     `#test-details` `Vertical`, mirroring `test_explorer.py`.
   - `on_mount()`: initialize the box (`display=False`, `border_title='Metadata'`,
     `wrap`, `markup`, placeholder text).
   - `_update_selected_test()`: write
     `console.expand_markup(get_testcase_metadata_markup(entry))` into it on
     selection; placeholder when no test is selected.
   - `BINDINGS`: `m → action_toggle_test_metadata` ('Toggle metadata');
     `r → action_toggle_metadata` ('Toggle run metadata'); drop the `g` binding.
   - `action_toggle_test_metadata`: change from "push `RichLogModal`" to "flip
     `#test-metadata` display" (same shape as `TestExplorerScreen.action_toggle_metadata`).
     `action_toggle_metadata` keeps delegating to
     `TwoSidedTestBoxWidget.toggle_metadata()`, now bound to `r`.
   - Remove the `RichLogModal` import.
2. **Delete `rbx/box/ui/screens/rich_log_modal.py`** — its only caller was this
   `g` action, so it becomes dead code — and its `#rich-dialog` CSS block
   (`app.tcss:121`).
3. **CSS**: `#test-metadata` is already styled for `RunTestExplorerScreen`
   (`app.tcss:89`) — no addition needed.
4. **`rbx/box/ui/CLAUDE.md`**: update the navigation map (`[g] -> RichLogModal`
   → `[m] -> docked metadata footer`, add `[r] -> run metadata`), drop the
   `RichLogModal` table row, and adjust the keybindings prose.

## Testing

A new Textual `Pilot` test driving `RunTestExplorerScreen` over a built-run
fixture (reusing the fixtures behind `tests/rbx/box/ui/test_run_ui.py`) asserts:

- `#test-metadata` is hidden by default.
- `m` reveals it and it shows the selected test's generation metadata.
- Changing the selection updates the footer's contents.
- `r` toggles the per-side run/eval metadata box.
- `g` no longer pushes a modal (the `ModalScreen` stack stays empty).

## Risk / notes

- Pure UI change; no schema or grading impact. Net dead-code removal (one screen
  file and one CSS block).
- Only behavioral regression: `g` becomes unbound — intentional, per the chosen
  key remap. The `?` help panel auto-reflects the new labels since it reads
  `BINDINGS`.

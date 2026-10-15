# Statement preview and LaTeX diagnostics (#909)

## Goal

Preview a built statement inside VS Code, next to its source, refreshed whenever a
build writes a new output; and report LaTeX and template errors as diagnostics on
the **source** line -- the `.rbx.tex` the setter wrote, not the generated
`statement.tex` they never see.

## Shape

rbx publishes; the extension renders. Everything an editor needs -- which outputs
exist, where they are, whether the last build of each one failed and why, on which
source line -- is written by rbx into one versioned artifact. The extension never
re-derives output names, never parses a LaTeX log, never knows how the overlay is
staged. Any other frontend (`rbx issues`, another editor, CI annotations) reads the
same file.

```
rbx st b ──► build/statement-en.pdf                (atomic write)
         └─► .rbx/statements/report.yml            (atomic, versioned)
                 outputs[]: kind/lang/variant/type/path/source/status/findings[]
VS Code  ──► watches report.yml ─► preview panel (pdf.js) + Problems panel
```

## 1. Source map: tagging lines at the lexer

A statement reaches pdflatex after two Jinja renders: the user's `.rbx.tex` is
rendered block by block, and the template splices the rendered blocks in with
`\VAR{problem.blocks.legend}`. Line numbers do not survive either step.

**Mechanism.** A Jinja extension (`sourcemap.LineTagExtension`) rewrites the token
stream: every `data` token gets an invisible tag `U+E000 <id>:<line> U+E001` at the
start of each source line with content. The tag is plain text, so it travels
through everything Jinja does -- blocks, loops, conditionals, `extends`, splicing a
block into a template -- and arrives in the final TeX exactly where the line it
came from landed. When rendered TeX is written into the overlay
(`sourcemap.emit`), the tags are stripped and each output line keeps the last tag
it carried. Output lines without a tag (a multi-line `\VAR{}` expansion, a blank
line) inherit the previous line's origin.

Why this and not the alternatives:

- *Materialize each block to a file and `\subimport` it*: changes every preset and
  user template (`blocks` is public template surface), and still loses lines to
  Jinja line statements and loops.
- *Search the source for the text near the error*: fragile, and wrong whenever the
  text came from a var.

The tags are ids, not paths, so a `{% filter upper %}` cannot corrupt them. Only
lines with non-whitespace content are tagged, so `if problem.blocks.notes` keeps
its meaning for a whitespace-only block. Tagging is on only inside
`sourcemap.tracking(...)`, which only the statement builds enter; `rbx vars`,
the var hints and every other render are untouched.

**Provenance.** The overlay is a copy, so a tag first names an overlay file. An
`Origins` table maps it back: *mounts* (overlay dir -> source dir: the chrome dir
and the problem dir, or `.problems/<SHORT>/` in a contest join), *aliases* (a
template staged by basename), and *sources* (files whose content is rendered from
the scratch `__input__.tex`, matched by content). Built by the two build entry
points, which already know every directory involved.

## 2. Findings

- **LaTeX.** pdflatex runs with `-file-line-error` and an unwrapped log
  (`max_print_line`), so every error reads `path:line: message`. Each one is
  mapped through the source map: a rendered file through its line map, a copied
  file (a user `\input`) through `Origins`, anything else (a system `.sty`) is
  kept as an unlocated finding.
- **Template.** A Jinja syntax error or an undefined variable is the most common
  failure and happens before pdflatex runs. Its location comes from Jinja itself
  (`TemplateSyntaxError.lineno`, or the template frames of an `UndefinedError`
  traceback), mapped through `Origins`.

Unlocated findings attach to the statement source, so they still surface.

## 3. The report

`<package>/.rbx/statements/report.yml`, written with `utils.write_text_atomic`,
`version: 1`, following the rules of the run report: structured never rendered,
read off never recomputed, versioned. One entry per output, upserted by
`(kind, name, language, variant, type)` after each statement finishes, so a build
of `en` leaves `pt`'s entry alone. Paths are relative to the package root when
inside it, absolute otherwise. A contest build writes the same file under the
contest root.

Final outputs are now written atomically too, so a viewer reloading on change
never reads half a PDF.

## 4. Extension

- **`rbx: Open Statement Preview`** (command, `editor/title` button on statement
  sources): a webview panel beside the editor rendering the PDF with **pdf.js**,
  bundled by esbuild, worker loaded from a blob under a strict CSP; works offline.
  The host reads the PDF and posts the bytes, so it works the same over Remote SSH,
  WSL and Codespaces.
- A picker lists the report's outputs; the default is the one whose `source` is the
  active editor. Reload on report change keeps page and zoom.
- Markdown outputs open in VS Code's own Markdown preview; TeX outputs open as text.
- *Build* button and opt-in `rbx.statements.buildOnSave` dispatch
  `rbx statements build` through the existing task dispatcher (#918).
- Findings join the existing `rbx` diagnostic collection.

## Out of scope

SyncTeX (click-to-source). The line map is the hard half of it: with
`-synctex=1`, a PDF position maps to a `statement.tex` line and the same map takes
it to the source.

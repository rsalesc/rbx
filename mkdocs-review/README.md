# mkdocs-review

Review documentation changes the way readers will see them. `mkdocs-review`
builds the base and head of a pull request with your own mkdocs setup, shows
the two rendered sites side by side with every changed block highlighted, and
turns the comments you leave on rendered text into a single GitHub review.

## Usage

```bash
# A pull request (needs the GitHub CLI, `gh`, logged in)
mkdocs-review 123

# Your branch against main, like a PR would see it
mkdocs-review main

# Any two commits
mkdocs-review v1.0..v1.1
```

The tool resolves both sides, builds each in a temporary `git worktree`, then
serves the review on `localhost` and opens your browser.

- **Changed pages** are listed on the left: `A` added, `D` removed, `M`
  modified, with counts of added, removed and changed blocks.
- **Both panes** show the real built pages, theme included. Added blocks are
  green, removed blocks red, edited blocks amber with the changed words marked.
  The panes scroll together; untick *Sync scroll* to move them independently.
- **`j` / `k`** jump to the next or previous change and carry on into the next
  page; **`n` / `p`** jump between pages.
- **Comment** by hovering a block in either pane and clicking **+**. Drafts
  are saved under `.mkdocs-review/` in your repository (git-ignored), so
  restarting loses nothing.
- **Submit review** posts every draft as one review. Each comment lands on the
  diff line it was matched to: a changed line of the page's source when one
  matches, otherwise a changed line elsewhere (an included partial, say). A
  comment that matches nothing goes into the review body with a quote of the
  block. The drawer shows where each comment will land before you submit.

Submitting needs a pull request; for ranges, comments stay local.

## Comparing against earlier versions

The right pane always shows the latest head. The **Compare against** menu
picks what the left pane shows:

- **merge base**, the default: everything the change does;
- any **commit** on the branch: what changed since then;
- for a pull request, any head that was **force-pushed** away, so a rebased PR
  keeps its history.

Versions someone reviewed are marked `reviewed by <login>`, so "what changed
since my last review" is one click. Every version is built in the background
after startup, reviewed ones and the newest first, and the menu shows each
one's progress. Picking one that is not built yet moves it to the front of the
queue. Pass `--no-prebuild` to build versions only when you pick them.

Comments still land on the pull request's diff. A comment on the left pane of
an earlier version quotes the text you saw, since GitHub's old side is the
merge base.

## Options

| Option | Default | |
|---|---|---|
| `--build-cmd` | `mkdocs build` | How to build the docs. `--site-dir DIR` (and `-f CONFIG` for a non-default config) is appended, unless the command uses `{site_dir}` / `{config}` placeholders. |
| `-f`, `--config` | `mkdocs.yml` | The mkdocs config, relative to `--repo-dir`. |
| `--repo-dir` | `.` | The repository to review. |
| `--content-selector` | `article`, `[role=main]`, `main`, `body` | CSS selector for the part of each page to diff; repeat for fallbacks. Navigation and other theme chrome outside it are ignored. |
| `--remote` | `origin` | Where pull request refs are fetched from. |
| `--port` / `--host` | any free port / `127.0.0.1` | Where to serve. |
| `--rebuild` | | Ignore cached builds. Builds are cached per commit and build command in `~/.cache/mkdocs-review`. |
| `--no-open` | | Do not open a browser. |
| `--no-prebuild` | | Build earlier versions only when picked in **Compare against**, not all of them in the background. |

Each side is built from a clean checkout, so the build command must work there.
With uv, `--build-cmd "uv run mkdocs build"` sets up the environment on first
use; pointing at an existing environment (`.venv/bin/mkdocs build`) is faster.

## Development

```bash
uv sync
uv run pytest
```

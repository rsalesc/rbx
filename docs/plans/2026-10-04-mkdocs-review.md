# mkdocs-review Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A local CLI that builds a docs PR's base and head with mkdocs, shows
both rendered side by side with the differences highlighted, and posts
comments made on rendered text as one GitHub PR review.

**Architecture:** A pure-Python core (block extraction, alignment, word
diff, source-line anchoring) annotates the built HTML pages; a stdlib HTTP
server serves both annotated sites plus a static single-page UI that hosts
them in two iframes and talks to an injected script via `postMessage`.
`git` and `gh` are driven through `subprocess`.

**Tech Stack:** Python 3.10+, beautifulsoup4, PyYAML, stdlib `http.server`,
vanilla JS/CSS; pytest + mkdocs (dev only) for tests. Managed with uv as a
standalone project in `mkdocs-review/`.

Design: `docs/plans/2026-10-04-mkdocs-review-design.md`.

---

All paths below are relative to `mkdocs-review/`. Run tests with
`uv run pytest` from that directory. Commit after each task with the
`/commit` conventions (`feat(mkdocs-review): ...`).

### Task 1: Project skeleton

**Files:** `pyproject.toml`, `README.md`, `src/mkdocs_review/__init__.py`,
`tests/__init__.py`; root `pyproject.toml` (sdist exclude).

- `pyproject.toml`: hatchling, `[project.scripts] mkdocs-review =
  "mkdocs_review.cli:main"`, deps `beautifulsoup4`, `pyyaml`; dev group
  `pytest`, `mkdocs`; own `[tool.ruff]` (single quotes, same rule set as the
  root) so it survives extraction.
- `uv sync` and confirm `uv run mkdocs-review --help` fails only because
  `cli` does not exist yet.

### Task 2: Block extraction (`blocks.py`)

Test first (`tests/test_blocks.py`):
- `extract_blocks(root)` returns block tags in document order: `p`, `li`,
  `h1`-`h6`, `pre`, `table`, `dt`, `dd`, `figcaption`, `summary`,
  `blockquote`; does not descend into `pre`/`table`; skips blocks whose own
  text (text excluding nested blocks) is empty and that hold no image.
- `own_text(block)` excludes nested block subtrees, `script`, `style`.
- `block_key(block)` is `tag:normalized own text` plus `[img src]` tokens.
- `find_main(soup, selectors)` returns the first match of
  `article`, `[role=main]`, `main`, `body`.

### Task 3: Alignment and word diff (`diff.py`)

Test first (`tests/test_diff.py`):
- `align(base_keys, head_keys)` returns rows `(base_idx|None,
  head_idx|None, status)` with status `same|changed|added|removed`;
  inside `replace` opcodes, blocks pair greedily in order when text
  similarity ≥ 0.4; unpaired become added/removed.
- `hunks(rows)` groups consecutive non-`same` rows; each hunk has a base and
  head anchor block (falling back to the nearest paired neighbour).
- `word_marks(base_words, head_words)` returns the indices of removed base
  words and added head words.

### Task 4: Page annotation (`annotate.py`)

Test first (`tests/test_annotate.py`):
- `diff_page(base_html|None, head_html|None, selectors)` returns a
  `PageDiff` with annotated HTML for both sides (blocks carry
  `data-mr-block`, `data-mr-pair`, `mr-added|removed|changed` classes;
  changed words wrapped in `span.mr-w-add`/`span.mr-w-del`), per-block info
  (text, status, changed words), hunks and counts.
- Missing side → every block on the other side is added/removed.
- Annotated HTML injects `/_mr/inject.css` and `/_mr/inject.js`
  (`data-side`).

### Task 5: Site and page mapping (`site.py`)

Test first (`tests/test_site.py`):
- `load_mkdocs_config(text)` tolerates unknown YAML tags (`!ENV`,
  `!!python/name:`) and returns `docs_dir` / `use_directory_urls` defaults.
- `dest_path(src, use_directory_urls)`: `a/b.md` → `a/b/index.html` or
  `a/b.html`; `index.md`/`README.md` → `index.html` in that directory.
- `list_pages(site_dir)` walks built `*.html`, skipping `404.html`,
  `assets/`, `search/`.
- `build_page_table(base, head)` unions both sides and attaches the source
  `.md` path (from `git ls-tree` of `docs_dir`) per side.

### Task 6: Unified diff parsing and anchoring (`anchor.py`)

Test first (`tests/test_anchor.py`):
- `parse_unified_diff(text)` → files with path, old path and lines
  (`+`/`-`/` `, old/new numbers).
- `anchor_comment(...)`: head-side comments match `+` lines of the page's
  source file, then its context lines, then `+` lines of any other changed
  file; base-side comments use `-` lines (LEFT). Lines are markdown-stripped
  and scored by token containment, with a bonus for the block's changed
  words. No acceptable match → `None` (goes to the review body).
- `build_review(drafts, anchors, head_sha)` builds the GitHub payload:
  anchored comments as `{path, line, side, body}`, the rest quoted in the
  review body.

### Task 7: git and gh plumbing (`gitops.py`, `github.py`)

- `resolve_target(spec)`: PR number → `gh pr view --json`, fetch
  `pull/N/head` and the base branch, base = merge-base; `A..B` → A vs B;
  `A...B` or a bare ref (`X` means `X...HEAD`) → merge-base.
- `build_site(repo, sha, cmd, cache_dir, rebuild)`: detached worktree,
  run the build command (`{site_dir}` placeholder or appended
  `--site-dir`), remove the worktree, cache by sha + command hash.
- `post_review(repo_slug, number, payload)` via `gh api --input -`.
- Tests: `tests/test_gitops.py` resolves ranges in a temporary git repo.

### Task 8: Server and drafts (`server.py`, `drafts.py`)

Test first (`tests/test_server.py`, server on port 0 in a thread):
- `GET /api/state`, `GET/PUT /api/drafts`, `POST /api/anchors`,
  `POST /api/submit`; `GET /site/<side>/<path>` serves annotated pages and
  raw assets with traversal protection; `/_mr/*` and `/` serve the UI.
- Drafts persist to `<repo>/.mkdocs-review/<key>.json`; the directory gets a
  `.gitignore` of `*`.

### Task 9: UI (`static/index.html`, `app.js`, `app.css`, `inject.js`, `inject.css`)

- Sidebar of changed pages (toggle to show all), two iframes, `j`/`k` hunk
  navigation, synced scrolling by pair id, hover `+` on blocks to draft a
  comment, drafts drawer with anchor preview, Submit button (disabled
  without a PR or gh).
- In-iframe link clicks navigate both sides; root-absolute links map into
  the site.

### Task 10: CLI and end-to-end

- `cli.py` wires it together, prints progress, opens the browser.
- `tests/test_e2e.py`: two-commit mkdocs repo in tmp, range mode, real
  `mkdocs build`, assert the changed page and its hunk appear in
  `/api/state`.
- Smoke test against this repository's docs.

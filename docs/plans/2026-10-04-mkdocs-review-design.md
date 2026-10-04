# mkdocs-review: side-by-side review of rendered docs PRs

## Problem

Reviewing a docs PR on GitHub means reading markdown diffs. The rich diff
does not understand mkdocs (macros, includes, admonitions, the theme), and
hosted previews show the new site without pointing at what changed. We want
one local tool that renders both sides with the real build, highlights the
differences, and turns comments on rendered text into a GitHub PR review.

## Scope

A standalone Python package in `mkdocs-review/`, with its own
`pyproject.toml` and tests, and no imports from `rbx`, so it can move to its
own repository unchanged.

Out of scope for v1: CI hosting, threaded replies, showing existing PR
comments.

## Design

### CLI

```
mkdocs-review <PR#|base..head> [--repo-dir .] [--config mkdocs.yml]
              [--build-cmd "mkdocs build"] [--port 0] [--no-open]
```

Resolves base and head SHAs (via `gh pr view` for a PR number, via
`git rev-parse` for a range), creates two temporary `git worktree`s, runs the
build command in each with `--site-dir` pointed at a work directory, and
serves the review UI on localhost.

### Page mapping

Reads `docs_dir` and `use_directory_urls` from the mkdocs config and maps
each `.md` file to its built HTML path with mkdocs's rules. A page is
`added`, `removed`, `modified` or `unchanged`; modified means its main
content differs. The main content selector is configurable (default
`article`, falling back to `[role=main]`, then `body`).

### Diff engine

Pure functions, no I/O. Main content is split into blocks (headings,
paragraphs, list items, `pre`, tables, admonitions, at the innermost
block level). Base and head blocks are aligned by normalized text with
`difflib.SequenceMatcher`; replaced pairs get a word-level diff. The result
per page is a manifest: for each side, the block index and its status
(`added`, `removed`, `changed`, `same`), plus word-level spans for changed
pairs and the alignment between sides.

### UI

Static HTML/JS, no framework. A sidebar lists changed pages. Two iframes
load the real built pages from the local server (base left, head right).
An injected script tags blocks in the same order the diff engine used,
applies highlights, scrolls the other side to the aligned block, and
supports `j`/`k` to jump between changes.

### Comments

Clicking a highlighted head block opens a comment box. Drafts persist in
`.mkdocs-review/<key>.json` inside the repository. On submit each comment is
anchored to a line in the PR diff: the block text is fuzzy-matched against
the added lines of the source file's hunks; if nothing matches well enough,
it becomes a file-level comment quoting the block. All comments go out as
one review (`event: COMMENT`) via `gh api`. The UI shows each comment's
anchor before submitting.

### Errors

A failed build prints its log and exits non-zero. Pages present on one side
only render as fully added or removed. Without `gh` auth (or for a plain
range) the tool still runs; submit is disabled and drafts stay local.

### Testing

Unit tests for page mapping, block diff and line anchoring on small
fixtures; one integration test that builds a two-commit mkdocs repository
in a temporary directory.

# Visualizations must be real files, not symlinks

## The problem

A visualization that rbx writes under `build/tests/<group>/visualization/` is a
symlink into the package's content-addressed storage:

```
build/tests/main/visualization/1-gen-000.html
  -> .rbx/.storage/1be329cf1b722b5bff15ce7d43e520dd41d45b63
```

The link carries the extension the setter declared. The file it points at
carries none, because a content-addressed blob is named by its digest.

Every consumer that types a file by its extension resolves the link first and
then finds nothing to go on. Measured on macOS:

| `file://` target | Chrome renders |
|---|---|
| `link.html` → extension-less blob | plain text, wrapped in `<pre>` |
| `link.html` → `blob.html` | parsed HTML |

`mdls` agrees: LaunchServices types the *symlink* `link.html` as `public.data`,
not `public.html`, so `open` does not route it to a browser as a page either.

This is not a Chrome quirk and not a VS Code quirk -- both resolve the link and
type the target. It bites anywhere a visualization is handed to something as a
path:

- the VS Code extension's testset panel, whose gallery draws an HTML
  visualization in an `<iframe>`; the webview resource is served with the
  resolved target's type, and an `<iframe>` honours a wrong `Content-Type`
  where an `<img>` is rescued by content sniffing. That is why the same panel
  renders SVG visualizations correctly and shows HTML ones as source.
- opening the built file by hand, from Finder or an editor.

`rbx ui` is already immune, and its workaround is the shape of the bug:
`utils.start_symlinkable_file()` copies the bytes to a temp directory
*preserving the file name* before calling `start_file()`. Every consumer paying
that tax separately is the thing worth fixing.

## Why not stop symlinking

Symlinks are load-bearing. `FileCacher.digest_from_symlink()` lets the cache
read an input's digest off the link instead of hashing the file
(`caching.py:125` and `caching.py:238`), and testsets are large. Dropping them
across the board trades a rendering bug for a rehash of every input on every
run.

The narrowing that makes this easy: `digest_from_symlink` is consulted for
**inputs** only. A visualization is a terminal artifact -- nothing in rbx ever
feeds one back in as an input. So visualizations can stop being symlinks at no
cost to the cache machinery, while `*.in` and `*.out` keep theirs.

## The change

Three edits.

1. `GradingFileOutput` gains a field:

   ```python
   # Whether the destination may be a symlink into the storage. Turn this off
   # for an artifact that is opened by something outside rbx: a symlink is
   # typed by its target, and a storage blob has no extension.
   symlink: bool = True
   ```

2. `_copy_hashed_files` (`grading/caching.py`) takes the symlink branch only
   when the output allows it, and otherwise falls through to the copy branch
   already sitting there.

3. `run_visualizer` (`box/visualizers.py`) declares its output with
   `symlink=False`.

### Why this is enough

`_copy_hashed_files` is the single materialization site: a cache miss reaches
it through `store_in_cache`, and a cache hit through `find_in_cache`. One flag
covers both, so a visualization restored from cache is a copy too.

The copy branch is not new code. It is what already runs on any storage backend
that does not offer `path_for_symlink`, so it is exercised in production today.

### What it costs

The visualization bytes are duplicated: once in storage, once in the build
tree. HTML and SVG visualizations are kilobytes. A large testset of PNG
visualizations is the only case where this is measurable, and it is bounded by
the size of the visualizations themselves.

### One deliberate gap

`_maybe_check_integrity` returns early unless the destination is a symlink
pointing at an existing storage file, so a copied visualization is no longer
tamper-checked. That check exists to notice a *storage* blob changing under a
link; a terminal artifact that nothing reads back does not need it. Widening it
to plain files is a separate decision, deliberately not taken here.

## What it fixes

`build/tests/**/visualization/*.html` becomes a real file with a real
extension. The panel's `<iframe>` gets `text/html`, and Finder, `open`, and
dragging the file into a browser all work. No change is needed on the extension
side.

## Alternatives considered

**Hard-link the artifact to the storage blob.** Same inode, so no duplicated
bytes, and the path a consumer sees is the file rather than a link to it. Also
more robust than a symlink, which dangles if storage is cleaned. It needs the
build tree and `.rbx/.storage` on one filesystem, and it needs the same
explicit opt-in as the copy, so it can replace the copy behind this same field
later without changing any call site.

**Give the storage blob the extension** (`<sha>.html` beside `<sha>`). Fixes
every artifact kind without touching call sites, but teaches a
content-addressed store about extensions -- one digest can be materialized
under several -- and costs an inode per (digest, extension) pair.

**Fix it in the VS Code extension**, by resolving and copying, or by inlining
the bytes. Leaves the build tree hostile to every other tool, and each new
consumer pays the tax again.

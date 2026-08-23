# `rbx vscode install` -- shipping the editor extension with the CLI

## Problem

The VS Code extension under `vscode/` is not published anywhere. A user who
wants it has to clone the repo, run `npm install && npm run package`, and
sideload the result by hand. Meanwhile the extension reads run artifacts under
`.rbx/runs/` whose layout moves with `rbx` itself, so an extension that lags the
installed `rbx` degrades quietly.

Both problems have the same shape: the CLI already knows which extension it
wants you to have, and -- when it runs inside an integrated terminal -- it can
both see what you actually have and install the right one.

## Why the integrated terminal makes this easy

VS Code and every fork prepend the app's own `bin` directory to `PATH` for
integrated terminals. `code` (or `cursor`, `windsurf`, `codium`) is therefore
callable even for users who never ran "Install 'code' command in PATH" -- which
is exactly the population this command targets.

In SSH remotes and devcontainers that same binary is a thin wrapper talking over
`VSCODE_IPC_HOOK_CLI`, and `--install-extension` installs into the *remote*
extension host. That needs no special case: the remote host is where `.rbx/runs/`
lives, so it is the right place for the extension anyway.

## Distribution: bundle the `.vsix`, do not publish

`code --install-extension <publisher>.<name>` resolves against a marketplace, and
the forks cannot use Microsoft's -- they resolve against Open VSX. Publishing
would mean two registries and two release cadences.

Installing from a local file works identically on every fork with no registry
involved:

```
<editor-bin> --install-extension /path/to/rbx-vscode-<version>.vsix --force
```

So the `.vsix` ships inside the wheel, as package data.

### Build pipeline

`mise run vscode:vsix` runs `vsce package` into `rbx/resources/vscode/`. vsce's
default output name is already `rbx-vscode-<version>.vsix`, so **the bundled
version is readable by globbing one directory** -- no zip to open on every run
and no sidecar metadata file that can drift from the artifact it describes.

`mise run build` runs `vscode:vsix` first, so `uv build` cannot produce a wheel
that silently lacks the extension.

### The hatchling trap

The `.vsix` is a build output, so it is gitignored -- and hatchling excludes
VCS-ignored files by default. Including it needs an explicit `artifacts` entry
on **both** build targets:

```toml
[tool.hatch.build.targets.wheel]
artifacts = ["rbx/resources/vscode/*.vsix"]

[tool.hatch.build.targets.sdist]
artifacts = ["rbx/resources/vscode/*.vsix"]
```

The sdist half is not redundant: `uv build` builds the sdist first and then the
wheel *from that sdist*, so a vsix dropped at the sdist stage never reaches the
wheel however the wheel target is configured. Verified by building both ways --
with the wheel entry alone, the wheel comes out empty.

Without this the wheel builds fine, tests pass, and the command breaks only for
real users. It is the one step of this design that fails invisibly.

When the `.vsix` is absent -- a dev checkout, an sdist -- `rbx vscode install`
fails with a pointer at `mise run vscode:vsix`, not a traceback.

## Command surface

```
rbx vscode install [--editor code|cursor|windsurf|codium|code-insiders] [--force]
```

A `rbx vscode` sub-app with exactly one command. No `status` (the nudge below
already answers "am I stale?") and no `uninstall` (the editor's own UI does
that). The group is named `vscode` even though it serves the forks too, because
that is the name users will reach for.

### Detecting the editor

`TERM_PROGRAM == 'vscode'` says we are in an integrated terminal but *not* which
editor -- every fork claims `vscode`. The fork comes from
`VSCODE_GIT_ASKPASS_NODE` / `VSCODE_GIT_ASKPASS_MAIN`, absolute paths into the
app bundle (`/Applications/Cursor.app/...`). Failing that, probe `PATH` in a
fixed order. `--editor` overrides both.

After a successful install the command prints the reload-window hint: VS Code
does not reliably activate a freshly installed extension in already-open windows,
and claiming otherwise would be a lie the user can see through.

## Version skew

Extension versioning stays **independent** of `rbx`'s -- the extension keeps its
own `0.x` line and can be fixed without an `rbx` release.

The nudge compares **extension version to extension version**: the bundled
`.vsix`'s version (from its filename) against the installed one (from the
editor's `extensions.json`). That is the question actually being asked -- "is
the extension in my editor older than the one my rbx ships?" -- and it needs no
new metadata field on either side.

It also behaves correctly if someone installs a *newer* extension from a
marketplace than the bundled one: it stays silent. A comparison routed through a
declared "rbx version I was built against" would nag in that case.

A declared floor (extension requires rbx >= X) answers the *reverse* question.
That is the skew direction `docs/plans/2026-08-11-vscode-extension-design.md`
already handles by graceful degradation, so it stays out until it earns its place.

### The check

`~/.vscode/extensions/extensions.json` (or `.cursor` / `.windsurf` /
`.vscode-server`, per the detected editor) is a JSON list of installed
extensions with `identifier.id` and `version`. Finding `rsalesc.rbx-vscode` in it
is a single file read -- sub-millisecond, no subprocess -- so it can sit at the
end of `rbx run` and of `rbx ui` without touching their timing.

For `rbx ui` that means when the UI *exits*, not at startup: a fullscreen TUI
wipes anything printed ahead of it, so a startup hint is a hint nobody sees.

The comparison is `utils.check_version_compatibility_between`, whose `OUTDATED`
case is exactly this condition.

Note that the extensions *directory* can hold several versions of the same
extension at once; `extensions.json` is the authoritative record of which one is
live.

### When it stays silent

- not in an integrated terminal (`TERM_PROGRAM != 'vscode'`)
- no `rbx` extension installed at all -- someone who has not opted in is not
  nagged into opting in
- installed version equal to or newer than the bundled one
- `extensions.json` missing, unreadable or malformed

One dim line. Never a blocking prompt, never an auto-install: installing an
extension into someone's editor is not a side effect `rbx run` should have.

## Testing

The logic factors into pure functions -- `detect_editor(env)`,
`installed_extension_version(extensions_root)`, `bundled_vsix()`, and the
comparison -- each testable against fixture env dicts and fixture
`extensions.json` files. Only the final `subprocess.run` is mocked.

No e2e: it would need a real editor.

`rbx/box/completion/_spec.py` needs regenerating for the new command.

# `rbx package moj --upload`: design

Issue [#755](https://github.com/rsalesc/rbx/issues/755).

`rbx package moj` builds a MOJ package and leaves it on disk. This adds `-u` /
`--upload`, which builds the package exactly as before and then uploads it to the
judge through the `moj` CLI -- the same CLI `rbx time --runner moj` already shells
out to. The difference from every other MOJ flow in rbx is what the upload is
*for*: `rbx time` uploads a throwaway probe to a private `rbxt-` problem, while
this uploads a package meant to be used.

## Where the built directory comes from

`moj upload <id> <dir>` wants the package **tree**, but `run_packager` builds into
a `TemporaryDirectory` and hands back only the `.zip`.

Unzipping that archive is not an option. `MojPackager` `chmod`s the checker
(`packager.py:1195`) and every `scripts/<lang>/` file (`packager.py:1337`) to
`0o755`, and Python's `zipfile.extract` does not restore mode bits -- the judge
would receive a package whose `compile.sh` and `run.sh` are not executable, which
fails on the server rather than locally.

So `run_packager` grows an optional `into_dir: Optional[pathlib.Path]`. When set,
`packager.package()` builds there instead of into the temp dir; nothing else
changes and no other packager is touched. The `moj` command owns its own
`TemporaryDirectory` and passes it in, which keeps the command's flow linear --
build, then upload -- rather than nesting the upload inside a callback.

## Resolving the problem id

A new `rbx/box/packaging/moj/upload.py`, a sibling of the packager, mirroring
`polygon/upload.py`.

```
login = await cli.whoami()          # existing; fails with "run `moj login`"
org   = env.extensions.moj.org or login
slug  = package_basename().lower()  # "<short>-<name>", or "<name>" outside a contest
id    = f'{org}#{slug}'
```

`package_basename()` is already the shared naming rule, so the id on the server
matches the artifact name on disk. MOJ's slug rule is stricter than rbx's: rbx
names allow uppercase and contest short names *are* uppercase letters, while MOJ
requires `^[a-z0-9][a-z0-9._-]{1,80}$`. Hence the lowercasing.

Two guards, both about failures that are otherwise confusing far from their cause:

- Validate the slug and the org (`^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$`) against
  MOJ's own rules, read off the CLI's `cmd_new`. A lowercased rbx name
  essentially always passes, but a server-side 400 on a slug says much less than
  we can say here.
- **Refuse a slug beginning with `rbxt-`.** That prefix is what `is_rbxt_id` uses
  to tell a throwaway timing problem from a real one. A problem legitimately
  named `rbxt-foo` would otherwise put a real package under an id that
  `rbx time --runner moj` believes it owns and may overwrite.

When `org` is absent the upload still happens -- under the setter's own login --
but it is warned about first: the problem lands in your **private personal org**,
visible to nobody else, and `extensions.moj.org` in `env.rbx.yml` is how it goes
somewhere shared.

## The env-level `moj` extension

`Extensions` in `rbx/box/extensions.py` carries only `boca` today; `moj` exists
solely as a *language*-level extension. Add `MojExtension(RejectsRemovedFields)`
to `packaging/moj/extension.py` with one optional field, `org`, and wire it as
`Extensions.moj`. This is a schema change, so `docs/schemas` regenerates.

## The command

```
rbx package moj -u [--calibrate]
```

The build is unchanged: verification, `--language` and `--calibrate` all behave
exactly as they do today, into a temp dir. Then:

1. `cli.whoami()`, resolve the id, warn if it is the personal org, print the
   target.
2. `cli.upload(id, dir)`. The server creates the problem when it does not exist --
   that is how `rbx time --runner moj` bootstraps its `rbxt-` problems -- so
   "create if missing" costs nothing. `display_title` and `languages` already ride
   along in the `.moj-meta.json` the packager writes, which `moj upload` requires.
3. Under `--calibrate` only: `cli.calibrate(id)`, and say it was queued.

There is **no confirmation prompt**. `-u` is itself the opt-in, as it is for BOCA
and Polygon.

The calibration is **not waited on**. `MojRunner._wait_for_calibration` exists
because a timing run cannot proceed on uncalibrated limits; a setter uploading a
package has nothing to block on, and a bounded poll here would only convert a
long server-side job into a long foreground one. `moj check <id>` reports the
state whenever they want it.

**`.moj-id` is never written.** The one at the package root is the binding
`rbx time --runner moj` reads: a real published id landing there makes
`ensure_moj_id` return a non-`rbxt-` id, and the runner then refuses to run at
all. Uploading from a temp dir keeps this safe for free, and the CLI excludes
`.moj-id` from the tar in any case.

## Non-goals

Stated because each would otherwise read as a bug.

- **Publishing.** `moj upload` neither publishes nor unpublishes: the server
  ignores `public` from a tar, and only `/problems/set-public` moves it. A newly
  created problem stays private until it is published by hand.
- **Creating the org.** `moj upload` creates the *problem*, not the *org*. An
  upload to an org that does not exist fails; rbx surfaces the CLI's message and
  names `moj mkdir <org>`. A pre-flight `moj org list`, to raise that before
  paying for a full build, is a possible follow-up rather than part of this.
- **Contest-level fan-out.** There is no `rbx contest package moj`, so this is
  single-problem only.

## Testing

Following the split already established in
`tests/rbx/box/runners/moj/test_cli.py`:

- Id resolution, the lowercasing, both validation refusals and the `rbxt-`
  refusal are pure unit tests.
- The upload's argv goes through the stub `moj` binary, so the assertion comes
  from a process that was really spawned.
- One packaging test that `into_dir` yields a tree with its `0o755` scripts
  intact -- the regression the directory-over-zip decision exists to prevent.

# Language edits through `<<: !include_deep` fragments (#887)

## Problem

`rbx contest create` from a multi-language preset, `rbx contest variant add`
and `rbx lang add/rm` all fail when a contest's `languages:` / `titles:` reach
`contest.rbx.yml` only through a `<<: !include_deep shared.rbx.yml` merge --
the layout a contest with variants naturally uses. The failed `create` also
leaves a half-copied directory behind.

Causes:

1. `template_languages` reads through `EditSession.target`, and
   `EditSession.resolve` raises on any key that exists only via a merge -- even
   for a read.
2. Every write is refused on purpose: `EditSession` cannot tell whether the
   caller meant to edit the shared value or shadow it locally.
3. The template is copied before the language list is decided and written.

A related, silent bug: under `!include_deep`, a nested key (`titles.es`)
supplied by the fragment is invisible to `resolve` when the includer has its
own `titles:` map, so `drop_title('es')` did nothing and the title survived.

## Decisions

- **Reads never go through an edit target.** `template_languages` reads the
  resolved tree.
- **`EditSession(path, follow_merges=True)`** edits the value where it
  *effectively* lives. `resolve` now models the merge exactly as
  `_merge_map` performs it: at each level, an ordered list of layers (the
  explicit map, the maps a parent's deep merge injected, then the map's own
  `<<` fragment). The first layer holding a key owns it; later layers merge
  into a map value only along deep edges.
  - A key set locally is edited locally (local wins, as before).
  - A key absent everywhere is created in the highest-precedence map at that
    level -- the root file at the top level, the fragment's map when the
    parent itself lives there (so `titles.fr` lands next to `titles.en`).
  - Several fragments can only supply a key through a chain (`<<:` takes one
    include); the merge order picks the effective one, so nothing is refused.
- **Strict mode stays the default** for every other caller, and now also
  refuses the nested deep-merge case above instead of silently shadowing it.
- **`rbx lang add/rm` confirm before editing a shared fragment** that another
  contest config also reaches: once, up front, before any target is touched.
  `--yes` skips the prompt; without a terminal and without `--yes` the command
  refuses. Package creation never prompts -- it only edits files it just
  created.
- **No partial directories.** Languages are picked before the template is
  copied, and `rbx contest create` / `rbx create` remove the destination when
  they created it and installation fails.

## Rejected

- Writing a local override into `contest.rbx.yml`: variants including the
  shared fragment would stop following `rbx lang add`.
- Asking "shared or local?" on every edit: impossible in a non-interactive
  `create`, and the intent for languages is clear.

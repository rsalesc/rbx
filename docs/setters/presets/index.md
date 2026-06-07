# Presets

!!! note
    This documentation is mainly targeted at head setters trying to create a contest
    from scratch.

    If you're just a setter that wants to contribute to an already existing contest,
    you can probably just clone the repository the head setters shared with you and skip
    this documentation altogether.

Presets is a feature that allows head setters to create a contest template that can be reused
across multiple contests.

A preset consists of four different pieces:

- A **contest template**: simply, a contest folder with some sensible defaults set that will
  be used to bootstrap a contest based on this preset
- A **problem template**: a problem folder with some sensible defaults set that will
  be used to bootstrap each problem based on this preset
- An **environment**: a configuration file that will be inherited by contests and problems
  created from this preset, and that {{rbx}} will use to configure its execution environment
- A **preset definition**: a `preset.rbx.yml` file that will be used to define the preset
  and its dependencies.

## Why a preset?

Presets strongly encourage code reuse across different contests. Besides that, it provides
a way to standardize the contest environment across different contests, making it easier
for setters to focus on creating the contest instead of configuring the environment.

Also, it makes it easier for setters to create new problems in a contest, offering a way for
the head setter to define a starting point for the problem.

Also, if the head setter wants to change the preset at some point, presets offer a way
to synchronize the changes across all the problems and contests that use the preset.

## Creating a preset

Creating a preset is a multi-step process that starts when the head setter runs the
`rbx preset create` command. By default, the command will create a new preset based
on {{rbx}} default preset.

```bash
rbx presets create
```

The command will prompt you for the name of the preset, and a GitHub repository URI that
can be used to reference to it.

```bash
└── your-preset-name
    ├── contest # (1)!
    ├── problem # (2)!
    ├── env.rbx.yml # (3)!
    └── preset.rbx.yml # (4)!
```

1. The contest template. This folder will be used to bootstrap each contest created from
   this preset.
2. A problem template. This folder will be used to bootstrap each problem created from
   this preset.
3. An environment file. This file will be used to configure the execution environment
   of {{rbx}} to be used in the contest.
4. A preset definition. This file will be used to define the preset and its dependencies.

The GitHub URI will be an unique identifier of your preset, and
can be used by other {{rbx}} users to fetch your preset from there if you decide to share
it publicly.

You can start from a preset of your own by specifying the `-p` flag.

!!! tip
    If you want to start from a preset of your own, you can do so by specifying the `-p`
    flag.

    ```bash
    rbx presets create -p your-base-preset
    ```

### Setting up the problem template

You can go to the problem template and modify it to your liking: package structure,
the `problem.rbx.yml` file, default testlib components, statement templates, etc. Everything
can be customized to fulfill your requirements.

Every problem created from this preset will be a clone of this folder, except for the folder name
and the `name` field of the `problem.rbx.yml` file, which will be changed to match your problem name.

!!! tip
    You can run {{rbx}} commands freely inside the problem template folder to test your template:
    any {{rbx}} internal folders will be ignored when inheriting from the preset.

### Setting up the contest template

You can go to the contest template and modify it to your liking: statement templates, `contest.rbx.yml` file,
etc. Everything can be customized to fulfill your requirements.

Usually, the contest template should have no problems initially. One should add problems with
`rbx contest add` after the contest has been created.

Every contest created from this preset will be a clone of this folder, except for the folder name
and the `name` field of the `contest.rbx.yml` file, which will be changed to match your contest name.

!!! tip
    You can run {{rbx}} commands freely inside the contest template folder to test your template:
    any {{rbx}} internal folders will be ignored when inheriting from the preset.

### Setting up the environment

The environment file will be used to configure the execution environment of {{rbx}} to be used
in the contest.

This file is rather complex, and its full reference documentation can be found [here](../reference/environment).

You can usually get away with the environment used by the `default` preset, which is
a good starting point for most contests. You can check its code [here](https://github.com/rsalesc/rbx/blob/main/rbx/resources/presets/default/env.rbx.yml).

### Setting up the preset definition

The preset definition file is a `preset.rbx.yml` file that will be used to define the preset
and its dependencies.

It can usually be broken down into a few sections, documented below for the default preset:

```yaml title="preset.rbx.yml"
# The name of the preset.
name: "default"

# The URI of the preset. Usually, refers to a GitHub repository.
# Here, refers to the "rbx/resources/presets/default" folder inside
# the "rsalesc/rbx" repository.
uri: "rsalesc/rbx/rbx/resources/presets/default"

# The template to use for creating problems from this preset.
# Refers to the `problem` folder in the preset definition.
problem: "problem"

# The template to use for creating contests from this preset.
# Refers to the `contest` folder in the preset definition.
contest: "contest"

# The environment to use for the contest and problems created from this preset.
env: "env.rbx.yml"

# Assets to be tracked and synced with the preset.
tracking:
  problem:
    - path: ".gitignore"
    - path: "documents/icpc.sty"
    - path: "documents/template.rbx.tex"
  contest:
    - path: ".gitignore"
    - path: "documents/icpc.sty"
    - path: "documents/template.rbx.tex"
    - path: "documents/contest.rbx.tex"
      symlink: true

```

The first few sections are pretty self-explanatory. Let's focus on the `tracking` section.

The `tracking` section describes a set of files that should be tracked by {{rbx}} when a problem
or contest is created from this preset.

If a file is tracked, it means that -- in theory -- it should be automatically synced with the preset.
Let's say you have a `.tex` file that is imported by all the problems in your contest. Let's say your
contest has 10 problems, but just now you realized you have to modify this `.tex` file to fix a typo.

Usually, this would mean you have to repeat the same change in all 10 problems. With presets, you
can just modify the `.tex` file in the preset definition, and run `rbx presets sync` inside your
contest folder, as long as the file is tracked.

This will sync all packages that use this preset with its newest changes, based on the set of tracked files.
Files that are not tracked **will not** be synced.

Tracked files can be specified both explicitly, or through Python-compliant glob patterns: `*.png`, `**/*.tex`, etc.

#### Symlink tracking

##### Flag-based symlink tracking

When you know for sure that a file should always be kept in sync (without manual intervention), you can
also create them as symlinks. Just mark the tracked file with the `symlink: true` flag, and {{rbx}} will
create a symlink to the file in the package instead of copying it. Then, every modification you do to it
will be instantly reflected in all other packages that use the preset.

##### Soft symlink tracking

An alternative way to create symlinks is to track files that are symlinks themselves. Let's suppose you have
the following structure:

```bash
contest/
├── documents/
│   └── icpc.sty -> ../../common_icpc.sty
problem/
└── documents/
    └── icpc.sty -> ../../common_icpc.sty
└── common_icpc.sty
```

In this case, you can track both `contest/documents/icpc.sty` and `problem/documents/icpc.sty` (no need for the `symlink: true` flag), and {{rbx}} will make sure to create a symlink to `common_icpc.sty` automagically for you.

This approach is particularly useful when you want to share a common file between the contest and the problem packages.

## Libraries

Competitive programming packages usually rely on a handful of third-party header libraries:
[testlib](https://github.com/MikeMirzayanov/testlib), [jngen](https://github.com/ifsmirnov/jngen),
[tgen](https://github.com/rsalesc/tgen), and similar. Instead of vendoring these files by hand in every
package, a preset can **declare** them once, and {{rbx}} will fetch, cache, and materialize them into
each problem and contest created from the preset.

This is configured through a `libraries:` block in `preset.rbx.yml`. It mirrors the shape of
[`tracking`](#setting-up-the-preset-definition): it has a `problem:` list (materialized into every
problem package) and a `contest:` list (materialized into every contest package).

```yaml title="preset.rbx.yml"
libraries:
  problem:
    - name: testlib            # logical name; also the `rbx download <name>` argument
      source: MikeMirzayanov/testlib   # owner/repo, full GitHub URL, a git URL, a raw download URL, or a local path
      path: testlib.h          # file (or directory) within the source repo; omit for a raw-URL source
      version: latest          # a commit prefix, a tag/branch/release, or "latest" (default-branch HEAD)
      dest: testlib.h          # where it is materialized in the package
      symlink: false           # copy to dest (false), or store under .local.rbx/libs/ and symlink dest to it (true)
      always_include: true     # also inject into the reserved __internal__/ dir so ANY source can #include it
      # include_as: bits/stdc++.h   # optional: include spelling when always_include (defaults to the basename of `path`)
  contest:
    - ...
```

### Per-entry fields

- **`name`** -- a logical name for the library. It is used as the cache key and as the argument to
  `rbx download <name>`.
- **`source`** -- where the library comes from. Accepts the same URI grammar used by the preset
  `uri`: an `owner/repo` shorthand, a full GitHub URL, a generic git URL, a raw download URL, or a
  local path.
- **`path`** -- the file (or directory) to take from the source repository. Omit it for a raw-URL
  source, since the URL already points directly at the file.
- **`version`** -- which revision to fetch: a commit prefix, a tag/branch/release name, or `latest`
  (the default-branch HEAD).
- **`dest`** -- where the library is materialized inside the package.
- **`symlink`** -- when `false` (default), the real file is copied to `dest`. When `true`, the content
  is stored under `.local.rbx/libs/<name>/` and `dest` becomes a relative symlink into it.
- **`always_include`** -- when `true`, the library is also injected into the reserved `__internal__/`
  directory so that **any** source can `#include` it without it having to resolve relative to the
  includer.
- **`include_as`** -- the include spelling to expose when `always_include` is set. Defaults to the
  basename of `path`. Use it for nested names such as `bits/stdc++.h`.

### How it works

- **Global cache.** Each library is fetched once into a global cache (`~/.rbx/libs/...`) and reused
  across all packages, so the same header is not downloaded again and again.
- **Materialization.** Declared libraries are materialized (and committed) directly into the package.
  In copy mode, the real file is written at `dest`. In symlink mode, the content is committed under
  `.local.rbx/libs/<name>/` and `dest` is made a relative symlink to it.
- **Reproducibility.** The committed materialized files **are** the pin -- there is no separate
  lockfile. To freeze a library's content, pin its `version` to a tag or commit. A `version` of
  `latest` re-resolves the default-branch HEAD on every `rbx presets sync`, so it can drift over time.
- **Syncing.** `rbx presets sync` re-fetches each library according to its `version` and overwrites the
  materialized files. Libraries are tool-managed, so local hand-edits to them are **not** preserved --
  if you need a customized copy, vendor it under a different `path`/`source` so it diverges from the
  declared library.
- **Network.** The first fetch of a remote library requires network access; there is no offline
  fallback for an uncached library.
- **Resolution.** With `always_include: true`, the library is placed in `__internal__/` and exposed via
  `-I__internal__`, so it is resolvable from any source directory. Without it, the library is only found
  when a source `#include`s it and the materialized file is resolvable relative to that source.

### Fetching libraries manually

You usually don't need to fetch libraries by hand -- they are materialized automatically when packages
are created and refreshed on `rbx presets sync`. When you do want to fetch them explicitly, use
`rbx download`:

```bash
# Fetch and materialize a single declared library, by name.
rbx download <name>
rbx download lib <name>   # equivalent, explicit alias

# Refetch all declared libraries.
rbx download lib

# Write a single library to a custom path instead of its `dest`.
rbx download <name> --into path/to/file.h
```

`rbx download testlib`, `rbx download jngen`, and `rbx download tgen` are convenience aliases that
resolve the declared library of the same name.

!!! note
    The `default` preset declares `testlib`, `jngen`, and `tgen`, all with `always_include: true`.
    Packages created from it therefore behave just like before -- those headers are available to every
    source -- but now they are versioned, fetched, and cached instead of being hardcoded into {{rbx}}.

## Using a preset

Presets can be used both when creating a contest or when creating a problem. Below
we detail all the commands where it can be used.

```bash
# Create a contest from a preset.
rbx contest create -p your-preset

# Initialize a contest (in the current directory) from a preset.
rbx contest init -p your-preset

# Add a problem to a contest (that already has its own preset), using the very same preset.
rbx contest add

# Create a standalone problem from a preset.
rbx create -p your-preset
```

In all variants above, a `.local.rbx` folder will be created at the root of the package. This folder stores a copy of the
preset, snapshotted at the moment the package was created. This way, your package has its own copy of the preset,
and you can either

1. Modify it at will, and those changes will not be reflected in the original preset;
2. Sync it to the original preset whenever you want.

If you modify your `.local.rbx` folder, but has already created some problems inside your contest that you
want to sync with the preset, you can do so by running `rbx presets sync` inside your contest folder.

This will sync all packages that use this preset with its newest changes. In other words, it will create missing
symlinks, and ask you if normal tracked files should be overridden or not.

## Sharing a preset publicly

You can share your preset publicly by uploading it to a GitHub repository. If your repository is
`<your-organization>/<your-preset-name>`, other uses can create a package from it by using

```bash
rbx contest create -p <your-organization>/<your-preset-name>
```

The preset will be cloned automatically, and then used as normal.

## Sharing a preset privately

You can share your preset privately, either through Git repositories or through other means. To initialize
a contest from a private preset, you can do the following:

```bash
mkdir my-new-contest
cd my-new-contest

# Clone the preset into .local.rbx
git clone https://github.com/my-organization/my-preset .local.rbx

# Initialize the contest
rbx contest init
```

This will initialize the contest from the `.local.rbx` preset, which you can initialize from a private
data source of your own.


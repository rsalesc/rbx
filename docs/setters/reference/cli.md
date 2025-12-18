# rbx

The `rbx` CLI is the main entry point for all operations. It provides a set of commands to manage problems, contests, and the environment.


**Usage:**
```bash
rbx [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `-c`, `--cache` | CHOICE | Which degree of caching to use. | `CACHE_ALL` |
| `--sanitized`, `-s` | BOOLEAN | Whether to compile and run testlib components with sanitizers enabled. If you want to run the solutions with sanitizers enabled, use the "-s" flag in the corresponding run command. | `False` |
| `--nocapture` | BOOLEAN | Whether to save extra logs and outputs from interactive solutions. | `True` |
| `--profile`, `-p` | BOOLEAN | Whether to profile the execution. | `False` |
| `--version`, `-v` | BOOLEAN | - | `False` |


---

## on

Run a command in the context of a problem (or a set of problems) of a contest.

**Usage:**
```bash
rbx on <PROBLEMS> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `PROBLEMS` | - | Yes |


---

## each

Run a command for each problem in the contest.

**Usage:**
```bash
rbx each [OPTIONS]
```


---

## edit (e)

Open problem.rbx.yml in your default editor.

**Usage:**
```bash
rbx edit [OPTIONS]
```


---

## build (b)

Builds the problem package.

This command compiles all generators, validators, and checkers. Then it generates inputs using the generator script and validates them with the validator. Finally, it generates the outputs using the main solution.

It is recommended to run this command before packaging the problem to ensure everything is up-to-date.


**Usage:**
```bash
rbx build [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |


---

## run (r)

Runs solutions against the testcases.

This is the primary way to test your solutions. You can run all solutions, a specific set of solutions, or only accepted solutions.

You can also filter which testcases to run against, by using the `--outcome` flag to only confirm that solutions match a certain expected outcome (e.g. TLE, WA).


**Usage:**
```bash
rbx run <SOLUTIONS> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `SOLUTIONS` | Path to solutions to run. If not specified, will run all solutions. | No |

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |
| `--outcome`, `-o` | TEXT | Include only solutions whose expected outcomes intersect with this. | - |
| `--nocheck` | BOOLEAN | Whether to not build outputs for tests and run checker. | `True` |
| `--detailed`, `-d` | BOOLEAN | Whether to print a detailed view of the tests using tables. | `False` |
| `--sanitized`, `-s` | BOOLEAN | Whether to compile the solutions with sanitizers enabled. | `False` |
| `--choice`, `--choose`, `-c` | BOOLEAN | Whether to pick solutions interactively. | `False` |


---

## time (t)

Estimate a time limit for the problem based on a time limit formula and timings of accepted solutions.

**Usage:**
```bash
rbx time [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--nocheck` | BOOLEAN | Whether to not build outputs for tests and run checker. | `True` |
| `--detailed`, `-d` | BOOLEAN | Whether to print a detailed view of the tests using tables. | `False` |
| `--strategy`, `-s` | TEXT | Strategy to use for time limit estimation (estimate, inherit). | - |
| `--auto`, `-a` | BOOLEAN | Whether to automatically estimate the time limit. | `False` |
| `--runs`, `-r` | INTEGER | Number of runs to perform for each solution. Zero means the config default. | `0` |
| `--profile`, `-p` | TEXT | Profile to use for time limit estimation. | `local` |
| `--integrate`, `-i` | BOOLEAN | Integrate the given limits profile into the package. | `False` |


---

## irun (ir)

Build and run solution(s) by passing testcases in the CLI.

**Usage:**
```bash
rbx irun <SOLUTIONS> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `SOLUTIONS` | Path to solutions to run. If not specified, will run all solutions. | No |

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |
| `--outcome`, `-o` | TEXT | Include only solutions whose expected outcomes intersect with this. | - |
| `--nocheck` | BOOLEAN | Whether to not build outputs for tests and run checker. | `True` |
| `--generator`, `-g` | TEXT | Generator call to use to generate a single test for execution. | - |
| `--testcase`, `--test`, `-tc`, `-t` | TEXT | Testcase to run, in the format "[group]/[index]". If not specified, will run interactively. | - |
| `--output`, `-O` | BOOLEAN | Whether to ask user for custom output. | `False` |
| `--print`, `-p` | BOOLEAN | Whether to print outputs to terminal. | `False` |
| `--sanitized`, `-s` | BOOLEAN | Whether to compile the solutions with sanitizers enabled. | `False` |
| `--choice`, `--choose`, `-c` | BOOLEAN | Whether to pick solutions interactively. | `False` |


---

## create (c)

Create a new problem package.

**Usage:**
```bash
rbx create [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--name` | TEXT | Name of the problem to create, which will be used as the name of the new folder. | - |
| `--preset` | TEXT | Preset to use when creating the problem. | - |


---

## stress

Runs stress testing on the current problem.

Stress testing allows you to find counter-examples where your solution fails (or where two solutions differ).

You usually provide a generator command (with random seed) and a reference solution (or validator/checker).


**Usage:**
```bash
rbx stress <NAME> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `NAME` | Name of the stress test to run (specified in problem.rbx.yml). | No |

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--generator`, `-g` | TEXT | Generator call to use to generate a single test for execution. | - |
| `--finder`, `-f` | TEXT | Run a stress with this finder expression. | - |
| `--timeout`, `--time`, `-t` | INTEGER | For how many seconds to run the stress test. | `10` |
| `--findings`, `-n` | INTEGER | How many breaking tests to look for. | `1` |
| `-v`, `--verbose` | BOOLEAN | Whether to print verbose output for checkers and finders. | `False` |
| `--sanitized`, `-s` | BOOLEAN | Whether to compile the solutions with sanitizers enabled. | `False` |
| `--description`, `-d` | TEXT | Optional description of the stress test. | - |
| `--descriptors`, `-D` | BOOLEAN | Whether to print descriptors of the stress test. | `False` |
| `--skip-invalid`, `--skip` | BOOLEAN | Whether to skip invalid testcases. | `False` |


---

## compile

Compile an asset given its path.

**Usage:**
```bash
rbx compile <PATH> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `PATH` | Path to the asset to compile. | No |

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--sanitized`, `-s` | BOOLEAN | Whether to compile the asset with sanitizers enabled. | `False` |
| `--warnings`, `-w` | BOOLEAN | Whether to compile the asset with warnings enabled. | `False` |


---

## validate

Run the validator in a one-off fashion, interactively.

**Usage:**
```bash
rbx validate [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--path`, `-p` | TEXT | Path to the testcase to validate. | - |


---

## unit

Run unit tests for the validator and checker.

**Usage:**
```bash
rbx unit [OPTIONS]
```


---

## header

Generate the rbx.h header file.

**Usage:**
```bash
rbx header [OPTIONS]
```


---

## environment (env)

Set or show the current box environment.

**Usage:**
```bash
rbx environment <ENV> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `ENV` | - | No |

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--install`, `-i` | TEXT | Whether to install this environment from the given file. | - |


---

## languages

List the languages available in this environment

**Usage:**
```bash
rbx languages [OPTIONS]
```


---

## stats

Show stats about current and related packages.

**Usage:**
```bash
rbx stats [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--transitive`, `-t` | BOOLEAN | Show stats about all reachable packages. | `False` |


---

## fix

Format files of the current package.

**Usage:**
```bash
rbx fix [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--print-diff`, `-p` | BOOLEAN | - | `False` |


---

## wizard

Run the wizard.

**Usage:**
```bash
rbx wizard [OPTIONS]
```


---

## clear (clean)

Clears cache and build directories.

**Usage:**
```bash
rbx clear [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--global`, `-g` | BOOLEAN | - | `False` |


---

## config (cfg)

Manage setter configuration (sub-command).

**Usage:**
```bash
rbx config [OPTIONS]
```


---

### path

Show the path to the setter config.

**Usage:**
```bash
rbx config path [OPTIONS]
```


---

### list (ls)

Pretty print the config file.

**Usage:**
```bash
rbx config list [OPTIONS]
```


---

### edit

Open the setter config in an editor.

**Usage:**
```bash
rbx config edit [OPTIONS]
```


---

### reset

Reset the config file to the default one.

**Usage:**
```bash
rbx config reset [OPTIONS]
```


---

## statements (st)

Manage statements (sub-command).

**Usage:**
```bash
rbx statements [OPTIONS]
```


---

### build (b)

Build statements.

**Usage:**
```bash
rbx statements build <NAMES> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `NAMES` | Names of statements to build. | No |

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |
| `--languages` | TEXT | Languages to build statements for. If not specified, build statements for all available languages. | - |
| `--output` | CHOICE | Output type to be generated. If not specified, will infer from the conversion steps specified in the package. | `PDF` |
| `--samples` | BOOLEAN | Whether to build the statement with samples or not. | `True` |
| `--vars` | TEXT | Variables to be used in the statements. | - |


---

## download (down)

Download an asset from supported repositories (sub-command).

**Usage:**
```bash
rbx download [OPTIONS]
```


---

### testlib

Download testlib.h

**Usage:**
```bash
rbx download testlib [OPTIONS]
```


---

### jngen

Download jngen.h

**Usage:**
```bash
rbx download jngen [OPTIONS]
```


---

### checker

Download a built-in checker from testlib GH repo.

**Usage:**
```bash
rbx download checker <NAME> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `NAME` | - | Yes |


---

### remote (r)

Download a remote code.

**Usage:**
```bash
rbx download remote <NAME> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `NAME` | - | Yes |

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `-o`, `--output` | TEXT | Whether to not build outputs for tests and run checker. | - |


---

## presets

Manage presets (sub-command).

**Usage:**
```bash
rbx presets [OPTIONS]
```


---

### create

Create a new preset.

**Usage:**
```bash
rbx presets create [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--name` | TEXT | The name of the preset to create. This will also be the name of the folder. | - |
| `--uri` | TEXT | The URI of the new preset. | - |
| `--preset`, `-p` | TEXT | The URI of the preset to init the new preset from. | - |


---

### update

Update preset of current package

**Usage:**
```bash
rbx presets update [OPTIONS]
```


---

### sync

Sync current package assets with those provided by the installed preset.

**Usage:**
```bash
rbx presets sync [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--update`, `-u` | BOOLEAN | Whether to fetch an up-to-date version of the installed preset from remote, if available. | `False` |
| `--force`, `-f` | BOOLEAN | Whether to forcefully overwrite the local assets with the preset assets, even if they have been modified. | `False` |
| `--symlinks`, `-s` | BOOLEAN | Whether to update all symlinks in the preset to point to their right targets. | `False` |


---

### ls

List details about the active preset.

**Usage:**
```bash
rbx presets ls [OPTIONS]
```


---

## package (pkg)

Build problem packages (sub-command).

**Usage:**
```bash
rbx package [OPTIONS]
```


---

### polygon

Build a package for Polygon.

**Usage:**
```bash
rbx package polygon [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |
| `--upload`, `-u` | BOOLEAN | If set, will upload the package to Polygon. | `False` |
| `--language`, `-l` | TEXT | If set, will use the given language as the main language. Leave unset if your problem has no statements. | - |
| `--upload-as-english` | BOOLEAN | If set, will force the main statement to be uploaded in English. | `False` |
| `--upload-only` | TEXT | Only upload the following types of assets to Polygon. | - |
| `--upload-skip` | TEXT | Skip uploading the following types of assets to Polygon. | - |


---

### boca

Build a package for BOCA.

**Usage:**
```bash
rbx package boca [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |
| `--upload`, `-u` | BOOLEAN | If set, will upload the package to BOCA. | `False` |
| `--language`, `-l` | TEXT | If set, will use the given language as the main language. Leave unset if you want to use the language of the topmost statement. | - |


---

### moj

Build a package for MOJ.

**Usage:**
```bash
rbx package moj [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |
| `--for-boca` | BOOLEAN | Build a package for BOCA instead of MOJ. | `False` |


---

### pkg

Build a package for PKG.

**Usage:**
```bash
rbx package pkg [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |


---

## contest

Manage contests (sub-command).

**Usage:**
```bash
rbx contest [OPTIONS]
```


---

### create (c)

Create a new contest package.

**Usage:**
```bash
rbx contest create [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--path` | TEXT | Path where to create the contest. | - |
| `--preset`, `-p` | TEXT | Which preset to use to create this package. Can be a named of an already installed preset, or an URI, in which case the preset will be downloaded.
If not provided, the default preset will be used, or the active preset if any. | - |


---

### init (i)

Initialize a new contest in the current directory.

**Usage:**
```bash
rbx contest init [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--preset`, `-p` | TEXT | Which preset to use to create this package. Can be a named of an already installed preset, or an URI, in which case the preset will be downloaded.
If not provided, the default preset will be used, or the active preset if any. | - |


---

### edit (e)

Open contest.rbx.yml in your default editor.

**Usage:**
```bash
rbx contest edit [OPTIONS]
```


---

### add (a)

Add new problem to contest.

**Usage:**
```bash
rbx contest add [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--path` | TEXT | Path where to create the problem. Name part of the path will be used as the problem name. | - |
| `--short-name` | TEXT | Short name of the problem. Will be used as the identifier in the contest. | - |
| `--preset` | TEXT | Preset to use when creating the problem. If not specified, the active preset will be used. | - |


---

### remove (r)

Remove problem from contest.

**Usage:**
```bash
rbx contest remove <PATH_OR_SHORT_NAME> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `PATH_OR_SHORT_NAME` | - | Yes |


---

### each

Run a command for each problem in the contest.

**Usage:**
```bash
rbx contest each [OPTIONS]
```


---

### on

Run a command in the problem (or in a set of problems) of a context.

**Usage:**
```bash
rbx contest on <PROBLEMS> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `PROBLEMS` | - | Yes |


---

### statements (st)

Manage contest-level statements.

**Usage:**
```bash
rbx contest statements [OPTIONS]
```


---

#### build (b)

Build statements.

**Usage:**
```bash
rbx contest statements build <NAMES> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `NAMES` | Names of statements to build. | No |

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |
| `--languages` | TEXT | Languages to build statements for. If not specified, build statements for all available languages. | - |
| `--output` | CHOICE | Output type to be generated. If not specified, will infer from the conversion steps specified in the package. | `PDF` |
| `--samples` | BOOLEAN | Whether to build the statement with samples or not. | `True` |
| `--vars` | TEXT | Variables to be used in the statements. | - |
| `--install-tex` | BOOLEAN | Whether to install missing LaTeX packages. | `False` |


---

### package (pkg)

Build contest-level packages.

**Usage:**
```bash
rbx contest package [OPTIONS]
```


---

#### polygon

Build a contest package for Polygon.

**Usage:**
```bash
rbx contest package polygon [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |
| `--language`, `-l` | TEXT | If set, will use the given language as the main language. | - |


---

#### boca

Build a contest package for BOCA.

**Usage:**
```bash
rbx contest package boca [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |


---

#### pkg

Build a contest package for PKG.

**Usage:**
```bash
rbx contest package pkg [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--verification-level`, `--verification`, `-v` | INTEGER | Verification level to use when building package. | `4` |


---

## testcases (tc, t)

Manage testcases (sub-command).

**Usage:**
```bash
rbx testcases [OPTIONS]
```


---

### view (v)

View a testcase in your default editor.

**Usage:**
```bash
rbx testcases view <TC> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `TC` | Testcase to view. Format: [group]/[index]. | Yes |

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--input`, `-i` | BOOLEAN | Whether to open only the input file in the editor. | `False` |
| `--output`, `-o` | BOOLEAN | Whether to open only the output file in the editor. | `False` |


---

### info (i)

Show information about testcases.

**Usage:**
```bash
rbx testcases info <PATTERN> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `PATTERN` | Testcases to detail, as a pattern. Might be a group, or a specific test in the format [group]/[index]. | No |


---

## tool (tooling)

Manage tooling (sub-command).

**Usage:**
```bash
rbx tool [OPTIONS]
```


---

### convert

**Usage:**
```bash
rbx tool convert <PKG> [OPTIONS]
```

**Arguments:**

| Name | Description | Required |
| :--- | :--- | :--- |
| `PKG` | The package to convert. | Yes |

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `-s`, `--source` | TEXT | The format to convert from. | - |
| `-d`, `--dest` | TEXT | The format to convert to. | - |
| `-o`, `--output` | TEXT | The output path. | - |
| `--language`, `-l` | TEXT | The main language of the problem. | - |


---

### boca

**Usage:**
```bash
rbx tool boca [OPTIONS]
```


---

#### scrape

Scrape runs from BOCA.

**Usage:**
```bash
rbx tool boca scrape [OPTIONS]
```


---

#### view

Open Textual UI to visualize BOCA submissions.

**Usage:**
```bash
rbx tool boca view [OPTIONS]
```

| Name | Type | Description | Default |
| :--- | :--- | :--- | :--- |
| `--contest-id`, `-c` | TEXT | Contest identifier to load (stored under app data). | - |


---

## 0.17.9 (2025-09-01)

### Fix

- add colors for c++ compilation
- add href to a few missing places

## 0.17.8 (2025-09-01)

### Fix

- fix manual scraper
- fix downlaod of remote solution

## 0.17.7 (2025-09-01)

### Fix

- update docs with pointers to uv
- add judge failed expected outcome for checker tests
- fix tee unbound variables

## 0.17.6 (2025-08-24)

### Fix

- fix leaked fds in Program

## 0.17.5 (2025-08-22)

### Fix

- ensure autojudge_new_sel is only checked for in newer versions of BOCA

## 0.17.4 (2025-08-22)

### Fix

- add option to print number of fds in tests to debug
- sort in a few globs to ensure deterministic ordering
- fix generator parser RECNAME expression

## 0.17.3 (2025-08-19)

### Fix

- make XML parser less strict with polygon packages

## 0.17.2 (2025-08-19)

### Fix

- add optional description to the stress test

## 0.17.1 (2025-08-18)

### Fix

- fix issue stack

## 0.17.0 (2025-08-16)

### Feat

- add names section in package

### Fix

- ensure title is not tied to statement in Polygon packager
- ensure title is not tied to statement in boca packager

## 0.16.4 (2025-08-15)

### Fix

- fix tests to unblock CI

## 0.16.3 (2025-08-15)

### Fix

- fix tool fetch
- get current version from __version__py

## 0.16.2 (2025-08-14)

### Fix

- add a few sensible defaults for Polygon xml
- ensure built-in presets are fetch from remote from a specific tag

## 0.16.1 (2025-08-12)

### Fix

- manually bump default preset version
- fix version files signature and update preset min version accordingly

## 0.16.0 (2025-08-12)

### Feat

- add min version field to presets

### Fix

- check for preset compatibility when installing/updating a preset
- fetch built-in presets from resources and check their version
- honor min_version checks when using a preset

## 0.15.0 (2025-08-11)

### Feat

- add commitizen version files
- **presets/info**: fix spacing in table
- **presets/icpc**: fix spacing in markright
- **presets/info**: fix eol
- **presets/info**: remove packages imported by icpc
- **presets/info**: declare \lang before importing icpc
- **presets/info**: declare geometry on documentclass

## 0.14.0 (2025-08-10)

### Feat

- add sol failures to issue stack
- add issue stack with contest-level error aggregation
- add model solution field to testsets
- build statements partially when one breaks
- add nested variables
- add option to integrate limits profile into package
- add limits to statements
- add new timing feature

### Fix

- add typing_extensions for compatibility with python<3.12 and TypeAliasType
- unqoute paths in sandbox glob
- add testlib to default preset
- improve solutions structure on preset
- fix a few tests
- use packager-specific limits profile when packaging
- fix caching issue with precompilation
- check for stack limit only on darwin
- use time profiles everywhere
- fix boca expander after refactor
- add problems to contest in lex order
- **cache**: symlink to cacher when copying compressed executable to sandbox
- fix a few unit tests
- fix time reporting on program.py
- add ridiculously buggy version flag
- ensure preset MIN_N variables is used in validator
- several improvements to preset statements

### Refactor

- delete other rbc stuff

## 0.13.8 (2025-07-19)

### Fix

- fix interactive sample line breaks
- fix Polygon statement build with vars

## 0.13.7 (2025-07-18)

### Fix

- fix scientific notation in statements
- optionally call killpg in sandbox

### Refactor

- remove two weird limit tests

## 0.13.6 (2025-07-14)

### Fix

- fix header.h serialization issues and write tests
- add tests for steps.run and fix memory usage
- kill solution when interactor finishes first with wa

### Refactor

- remove a few debugging assets
- delete processing_context.py (unused)
- delete old test.py stupidsandbox tester
- erase timeit

## 0.13.5 (2025-07-13)

### Fix

- fix copytree gitignore
- capture interaction in new sandbox
- allow for 64-bit rbx.h vars
- fix digest integrity checks
- rewrite to use a new stupid sandbox
- ensure checker messages are properly truncated everywhere
- ensure we don't check caching integrity on write
- ensure pipes are not captured when specified manually in generators
- add proper escaping in rbx ui
- add tests for default preset
- remove console log for nocheck

### Refactor

- delete unused fifo code
- remove deprecated isolate code
- move problem testdata
- clean up check functions in steps.py

## 0.13.4 (2025-07-10)

### Fix

- use relpath compatible with python < 3.12
- use sqlitedict instead of shelve
- add new tests for checker communication
- fix vars formatting for rbx.h
- **statement**: ensure flags are propagated to statements correctly

### Refactor

- delete old rbc assets

## 0.13.3 (2025-07-04)

### Fix

- ensure certain deps are not imported

## 0.13.2 (2025-07-04)

### Fix

- regenerate lock

## 0.13.1 (2025-07-04)

### Fix

- **stress**: fix stress name
- add contest-level packager for boca
- **preset**: remove generation section in default preset yaml
- ensure interactor and main are only compiled when output generation is necessary

## 0.13.0 (2025-07-04)

### Feat

- **packaging**: add language parameter to polygon packagers
- **tool**: add importer and converter from polygon to boca (problem)
- **contest**: makes rbx each available as an alias to rbx contest each

## 0.12.0 (2025-07-03)

### Feat

- **package**: add suppot for specifying generators by path
- **package**: support globs on solutions

### Fix

- **preset**: update default preset to use getVar() instead of opt()
- **cache**: ensure dir of symlinks are created before the symlink itself
- make sure --vars does not override -v in statement commands
- ensure CRLF are automatically fixed
- add check for crlf when building tests
- show proper error when invalid generator is referenced by script
- use enum in preset instead of alias
- improve texliveonfly call
- fix preset interactive example spacing
- improve default preset .gitignore

## 0.11.2 (2025-07-02)

### Fix

- install tex in builder

## 0.11.1 (2025-07-02)

### Fix

- ensure joined type does not superseed install-tex

## 0.11.0 (2025-07-02)

### Feat

- add option to install tex missing packages automatically with tinytex

### Fix

- **preset**: uncomment modern font in default preset
- fix editorial in presets

## 0.10.3 (2025-07-01)

### Fix

- make sure copytree respects symlnks in presets
- add editorial block to template

## 0.10.2 (2025-07-01)

### Fix

- temporarily disable rbx fix on pkg creation
- fix order
- fix problem_template.rbx.tex

## 0.10.1 (2025-07-01)

### Fix

- do not get presets from resources

## 0.10.0 (2025-07-01)

### Fix

- fix version

## 0.10.0rc0 (2025-07-01)

### Feat

- **statement**: add support for pandoc markdown wirh rbxmd

## 0.9.2 (2025-07-01)

### Fix

- fix cache level on pydantic

## 0.9.1 (2025-06-30)

### Fix

- add caching to default config templates
- fix shelve open call type
- check integrity of symlinks

## 0.9.0 (2025-06-30)

### Feat

- **preset**: add support for symlinks in presets
- **presets**: add rbx presets create

### Fix

- **preset**: ensure symlinks are always copied
- replace .resolve() calls with utils.abspath()
- update preset tracking
- add prompts to all package creation commands
- **cache**: do not cache in irun, except for when passing -t/-tc
- fix none issue with run.log.time

## 0.8.0 (2025-06-28)

### Feat

- **remote**: add @main shortcut to refer to main solution
- **stress**: make stress support simple finder expression with just the solution name
- **stress**: support remote solutions in stress
- **cache**: use global cache for precompilation
- **debug**: add debug context
- **cache**: refactor metadata and introduce executable compression
- **cache**: add grading context for controlling cache behavior

### Fix

- **cache**: ensure compilation is not cached for remote solutions too
- **cache**: disable caching for remote solutions
- **stress**: cache only compilation in stress tests
- add progress notices to stress tests
- **stress**: support interactive problems
- **stress**: migrate stress tests to use run_solution_on_testcase
- migrate a few occurrences of @functoos.lru_cache
- fix bug when teeing interactive problem communication
- use orderedset to store tracked solutions to guarantee run order
- **cache**: add global cache to stats
- **cache**: convert src inputs to digests when file symlinks to digest
- add profiling utilities
- ignore property error
- **cache**: symlink to storage where possible
- **cache**: add symlink to backend when available from get_file
- use description to signal sanitization
- **cache**: add Filecacher in a few more places
- **run**: show error when running with non-existing solutions
- **preset**: fix default preset
- fix default preset olymp.sty

## 0.7.0 (2025-06-23)

### Feat

- **preset**: add `rbx contest init` command
- **lint**: add YAML linting config to go hand-to-hand with VSCode
- **lint**: add linting for presets

### Fix

- **lint**: fix Problem -> Package schema name

## 0.6.1 (2025-06-23)

### Fix

- fix publishing

## 0.6.0 (2025-06-23)

## 0.29.0 (2026-02-25)

### Feat

- **ui**: add tabbed command queuing and input box to command app
- create command app

### Fix

- make rbx on run in non-ui mode when only a single problem of interest
- **ui**: enforce sequential execution for user-initiated commands in command app
- **ui**: add border to CommandPane in command app

### Refactor

- **ui**: replace LogDisplay with vendored Toad CommandPane

## 0.28.2 (2026-02-24)

### Fix

- ensure hash duplication warnings point to metadata
- add flag to compile all assets
- ensure warnings are parsed correctly after ansi code stripping

## 0.28.1 (2026-02-23)

### Fix

- handle BraceGroup and escaped dollar in polygon TeX validation

## 0.28.0 (2026-02-23)

### Feat

- ensure polygon blocks come directly from statement building and preprocess+validate them
- add JSON serialization for MacroDefinitions
- add expand_macros with iterative hybrid TexSoup + text replacement
- add collect_macro_definitions with recursive file traversal
- add extract_definitions for parsing macro definitions from TeX
- add MacroDef and MacroDefinitions data model for demacro

### Fix

- ensure only samples and statements are built when uploading
- make sure vars can be used in .tex for tests
- bump version and push
- ignore macros in tex->polygon transformation
- add support for macros block in default preset
- sync pre-commit ruff version with project and fix lint errors
- remove xdg-open command from wsl system (#385)

## 0.25.4 (2026-02-18)

### Fix

- update uv lock

## 0.25.3 (2026-02-18)

### Fix

- fix issue with ui visualizers

## 0.25.2 (2026-02-18)

### Fix

- limit to Python3.13 fort now
- fix event loop issue on Python3.14

## 0.25.1 (2026-02-18)

### Fix

- fix issue with visualizers and rbx ui
- prime template before rendering blocks
- use version range instead of exact major pin in upgrade command
- add dotenv loading
- fix a few extra tests and code
- migrate commitizen config

## 0.25.0 (2026-02-07)

### Feat

- migrate from poetry to uv

### Fix

- fix version provider for commitizen
- delete dangling svg
- Rename CLAUDE.md -> AGENTS.md
- remove poetry badge
- disable FMA on ARM
- show warning when not using rbx time
- dedup issue stack messages
- add issue severity markers
- handle typer.Exit() in rbx ui apps
- make rbx ui visible

## 0.24.0 (2026-02-01)

### Feat

- add visualizers

### Fix

- interactive mode docs
- add special code to visualizers
- add interactive to visualizers
- fall back to visualizer hwen no solution visualizer
- fully refactor visualizers
- add output_from to visualizers
- add ui visualizers
- fix novalidate typo
- add package size to packager

## 0.23.8 (2026-01-27)

### Fix

- fix packager statemment building
- improve build samples with sense of progress
- fixed output validation
- fix missing async

## 0.23.7 (2026-01-26)

### Fix

- fix inheritance bug
- fix stress test command
- show generator call along error
- add validate flags
- add --no-validate to irun

## 0.23.6 (2026-01-23)

### Fix

- fix fuzz tests
- small fix in error msg
- ensure output validators are also run for .out files

## 0.23.5 (2026-01-22)

### Fix

- warn about symlink issue with git-on-windows
- add bit to avoid building samples in statements
- show nice error messages about rbx version when parsing fails
- fix stats
- ensure clean can clean contests
- print better errors

## 0.23.4 (2026-01-19)

### Fix

- add check for .out output files
- build statement samples from generation entries, and handle .out and .ans separately
- add manual ans verification
- modify original sci function

## 0.23.3 (2026-01-17)

### Fix

- fix relative assets during contest statement building

## 0.23.2 (2026-01-17)

### Fix

- add --novalidate flag to commands
- add note that users can skip validation when building
- show error when summarization fails for problem within a contest

## 0.23.1 (2026-01-16)

### Fix

- improve rbx sum and add a detailed mode
- add rbx summary

## 0.23.0 (2026-01-10)

### Feat

- add fuzz tests to stresses

### Fix

- add group name to validator calls
- fix expected score validation
- add group deps to points problems
- add basic scoring implementation with a few todos
- slight refactor to accomodate for new scoring features
- skip invalid test cases in fuzz tests
- add .interaction file to docs
- add --slowest flag to stress tests
- add duplicate test check
- add polygon validation utils but dont use just yet
- fix contest statement expansion during inheritance
- add tikzpictures that are expanded into pdfs
- add externalization params when building statements for polygon
- add tikz externalization to build process
- add a bunch of texsoup utils
- fix a few issues

## 0.22.2 (2025-12-27)

### Fix

- add -p variant for --profile
- have a global profile flag to control which profile is used
- add custom time controls for stress tests
- consolidate limits profile function
- fix a few type findings
- check preset version first thing in rbx
- add a few predownloaded assets to rbx to improve usability in a no-connection scenario
- add solution tags
- tell current profile TL in rbx time
- show a issue when solution is producing too much stderr
- fix method import
- teach user how to bypass version constraint in preset error
- warn on duplicate generator calls in testplan
- add duplicate call error to stress tests
- show errors when certain commands do not exist
- add vars to high-level problem context

### Refactor

- fix casing of variables

## 0.22.1 (2025-12-21)

### Fix

- fix remaining tests
- fix a couple weird tests
- fix a failing test in generator scripts
- fix a few generator script tests

## 0.22.0 (2025-12-21)

### Feat

- add inheritance to problem statements

### Fix

- add titles to contests
- inheriting contest vars when using inheritFromContest
- fix expander tests
- fix rbxtex statements
- reorder polygon upload docs

## 0.21.4 (2025-12-19)

### Fix

- add validator to polygon upload

## 0.21.3 (2025-12-19)

### Fix

- ensure other manual tests are uploaded to polygon

## 0.21.2 (2025-12-17)

### Fix

- correctly upload polygon statement assets
- handle exceptions properly in thread pools during polygon upload
- always kill processes in pipe.c

## 0.21.1 (2025-12-01)

### Fix

- ensure interactive process are ordered and we track order of visit

## 0.21.0 (2025-11-27)

### Feat

- add output validators when building and validating
- **\**: create unit test parser
- add parser for testplan and testgroups

### Fix

- fix BOCA interactive run when code is not chrooted
- read explanation files from tex accompanying samples
- add parsing for testplan:line tests
- print what solution is being used to generate outputs
- add unit tests new parsing
- fix parsing issues with input blocks
- be more lenient with whitespaces in unit parser
- fix whitespace normalization within input blocks in parsers
- add expectation support in unit test parser
- add support for bracket delimited input/output
- support @input in statement
- structure generation input coming from testplans
- smart delete solution in polygon
- save generator scripts in polygon uplaod
- use correct language in validator
- upload polygon solutions with correct lang
- upload statement resources in parallel
- parallelize solution uplaod to polygon
- fix image names in statement resources when uploading to polygon

## 0.20.1rc6 (2025-11-08)

### Fix

- add upload filtering for polygon

## 0.20.1rc5 (2025-11-08)

### Fix

- fix polygon schema
- add keybind based filters
- add small fetch optimization
- add sentinel for failures
- show loading box while loading code
- add fixes to boca view

## 0.20.1rc4 (2025-11-07)

### Fix

- ensure view refreshes do not deselected things
- pause refresh with zero
- ui friendly magenta

### Refactor

- \remove unused code

## 0.20.1rc3 (2025-11-07)

### Fix

- fix compilation error in scraping

## 0.20.1rc2 (2025-11-07)

### Fix

- improve width size

## 0.20.1rc1 (2025-11-07)

### Fix

- add substring team filter
- select code and show on row highligh

## 0.20.1rc0 (2025-11-07)

### Fix

- deal with small diffs
- add two types of diffs
- prefetch solutions in boca scraper view
- vibe code a boca view
- add code review for remote boca run

## 0.20.0 (2025-11-07)

### Fix

- fix boca scraper for remote download runs
- fix no caching of remote solutions
- add empty statement in BOCA when one is not present
- ensure builtin checker is read when path does not exist
- change > to >= when checking for TL when printing operator along with the time
- ensure AC testcases with warnings are render by live run reporter
- make compiled file relative to package

## 0.20.0rc11 (2025-11-06)

### Fix

- fix relpath walk up

## 0.20.0rc10 (2025-11-04)

### Fix

- fix a few typing errors
- fix function in rbx_ui
- schedule hard kill if program does not finish fast enough after interrupt
- fix hanging 0 testcase

## 0.20.0rc9 (2025-11-04)

### Fix

- handle ctrl+C in stress tests
- handle ctrl+C through a try-catch block
- make paths relative in irun
- ensure ctrl+C does not show stacktrace

## 0.20.0rc8 (2025-11-04)

### Fix

- optimize detailed table

## 0.20.0rc7 (2025-11-04)

### Fix

- fix issues with typing
- fix timing per language
- fix solution href in compilation error

## 0.20.0rc6 (2025-11-03)

### Fix

- reintroduce OK to rbx run
- add TL in timing summary and color appropriately things that should be info

## 0.20.0rc5 (2025-11-03)

### Fix

- add hilite
- split good and pass in timing summary

## 0.20.0rc4 (2025-11-03)

### Fix

- put rbx irun back in a state similar to rbx run
- ensure issues stack rule is printed as red
- ensure "slow" is printed as a TLE verdict
- print number of testcases in each group

## 0.20.0rc3 (2025-11-03)

### Fix

- use red background for failed
- use relative runs folder in solution header
- fix prerelease script

## 0.20.0rc2 (2025-11-03)

### Fix

- update packaging module

## 0.20.0rc1 (2025-11-03)

### Fix

- fix semver

## 0.20.0rc0 (2025-11-03)

### Feat

- colorize solutions with href
- add live run reporter

### Fix

- disable typer autocompletion
- show test metadata when testcase fails the validation
- fix checker compilation error
- fix duplicate parameter -o in irun
- handle kbi in ask commands in rbx time

## 0.19.11 (2025-10-21)

### Fix

- fix compilation issue with stress tests

## 0.19.10 (2025-10-17)

### Fix

- passes through all validators in one off commands

## 0.19.9 (2025-10-17)

### Fix

- run all validators

## 0.19.8 (2025-10-14)

### Fix

- fix GenerationMetadata for @copy entries

## 0.19.7 (2025-10-14)

### Fix

- add overrides for pypy compilation

## 0.19.6 (2025-10-14)

### Fix

- few cosmetic fixes

## 0.19.5 (2025-10-14)

### Fix

- show a nice error when editor is not found

## 0.19.4 (2025-10-11)

### Fix

- add mode to checker to support custom BOCA checkers

## 0.19.3 (2025-10-09)

### Fix

- ensure boca language utils honor env language finding per extension
- add support for additional extensions in languages
- ensure .limits folder is not created when reading limits file

## 0.19.2 (2025-10-09)

### Fix

- add configuration for fallback checker to match box behavior

### Refactor

- use get_checker_or_nil functions to check for main checker

## 0.19.1 (2025-10-08)

### Fix

- add extraValidators globally
- add glob support for extraValidators
- refactor get_globbed_code_items
- fix f-string quoting
- support adding stress findings to box testplans
- make sure stress tests add generatorScript.path to the yml
- only use generators with a matching extension/language
- add custom build dirs to presets

## 0.19.0 (2025-10-08)

### Feat

- add box testplan format
- add @copy to generator scripts
- add beta wizard backkend

### Fix

- use builtin checkers automagically
- use generator script root only for generators
- fix lookup by extension
- fix sanitization in irun
- cache transiently when sanitization is enabled
- use line flush when building samples
- add warning that wizard was vibe coded
- fix model routing
- fix default value for strategy

## 0.18.12 (2025-09-12)

### Fix

- support round in safeeval

## 0.18.11 (2025-09-12)

### Fix

- add --auto flag for rbx time

## 0.18.10 (2025-09-12)

### Fix

- show tls for BOCA packaging

## 0.18.9 (2025-09-12)

### Fix

- fix issue with limit modifiers
- use safeeval for timing formulae
- use safeeval for commands
- add safeeval for file mapping

## 0.18.8 (2025-09-12)

### Fix

- rollback Java class detection logic in BOCA
- add ability to specify language when building boca package

## 0.18.7 (2025-09-11)

### Fix

- add pypy3 support to boca

## 0.18.6 (2025-09-09)

### Fix

- skip invalid tests when generation fails in stress

## 0.18.5 (2025-09-09)

### Fix

- small fix on print error header

## 0.18.4 (2025-09-08)

### Fix

- dump statement build artifacts of contest into a dir
- ensure compilation errors are skipped in rbx run
- add option to skip invalid tests in stress
- invert order of teeing to make interactive merged output less flaky
- fix more tests

### Refactor

- small cosmetics changes

## 0.18.3 (2025-09-04)

### Fix

- fix several rbx/boca language integration issues

## 0.18.2 (2025-09-03)

### Fix

- fix default BOCA flags in env
- update preset to match all files

## 0.18.1 (2025-09-02)

### Fix

- fix statement matching

## 0.18.0 (2025-09-02)

### Feat

- support kotlin in boca
- add support for kotlin
- add support for envrc

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

## 0.27.0 (2026-02-22)

### Feat

- ensure polygon blocks come directly from statement building and preprocess+validate them
- add JSON serialization for MacroDefinitions
- add expand_macros with iterative hybrid TexSoup + text replacement
- add collect_macro_definitions with recursive file traversal
- add extract_definitions for parsing macro definitions from TeX
- add MacroDef and MacroDefinitions data model for demacro

### Fix

- make sure vars can be used in .tex for tests
- bump version and push
- ignore macros in tex->polygon transformation
- add support for macros block in default preset
- sync pre-commit ruff version with project and fix lint errors
- remove xdg-open command from wsl system (#385)

## 0.25.4 (2026-02-18)

### Fix

- update uv lock

## 0.25.3 (2026-02-18)

### Fix

- fix issue with ui visualizers

## 0.25.2 (2026-02-18)

### Fix

- limit to Python3.13 fort now
- fix event loop issue on Python3.14

## 0.25.1 (2026-02-18)

### Fix

- fix issue with visualizers and rbx ui
- prime template before rendering blocks
- use version range instead of exact major pin in upgrade command
- add dotenv loading
- fix a few extra tests and code
- migrate commitizen config

## 0.25.0 (2026-02-07)

### Feat

- migrate from poetry to uv

### Fix

- fix version provider for commitizen
- delete dangling svg
- Rename CLAUDE.md -> AGENTS.md
- remove poetry badge
- disable FMA on ARM
- show warning when not using rbx time
- dedup issue stack messages
- add issue severity markers
- handle typer.Exit() in rbx ui apps
- make rbx ui visible

## 0.24.0 (2026-02-01)

### Feat

- add visualizers

### Fix

- interactive mode docs
- add special code to visualizers
- add interactive to visualizers
- fall back to visualizer hwen no solution visualizer
- fully refactor visualizers
- add output_from to visualizers
- add ui visualizers
- fix novalidate typo
- add package size to packager

## 0.23.8 (2026-01-27)

### Fix

- fix packager statemment building
- improve build samples with sense of progress
- fixed output validation
- fix missing async

## 0.23.7 (2026-01-26)

### Fix

- fix inheritance bug
- fix stress test command
- show generator call along error
- add validate flags
- add --no-validate to irun

## 0.23.6 (2026-01-23)

### Fix

- fix fuzz tests
- small fix in error msg
- ensure output validators are also run for .out files

## 0.23.5 (2026-01-22)

### Fix

- warn about symlink issue with git-on-windows
- add bit to avoid building samples in statements
- show nice error messages about rbx version when parsing fails
- fix stats
- ensure clean can clean contests
- print better errors

## 0.23.4 (2026-01-19)

### Fix

- add check for .out output files
- build statement samples from generation entries, and handle .out and .ans separately
- add manual ans verification
- modify original sci function

## 0.23.3 (2026-01-17)

### Fix

- fix relative assets during contest statement building

## 0.23.2 (2026-01-17)

### Fix

- add --novalidate flag to commands
- add note that users can skip validation when building
- show error when summarization fails for problem within a contest

## 0.23.1 (2026-01-16)

### Fix

- improve rbx sum and add a detailed mode
- add rbx summary

## 0.23.0 (2026-01-10)

### Feat

- add fuzz tests to stresses

### Fix

- add group name to validator calls
- fix expected score validation
- add group deps to points problems
- add basic scoring implementation with a few todos
- slight refactor to accomodate for new scoring features
- skip invalid test cases in fuzz tests
- add .interaction file to docs
- add --slowest flag to stress tests
- add duplicate test check
- add polygon validation utils but dont use just yet
- fix contest statement expansion during inheritance
- add tikzpictures that are expanded into pdfs
- add externalization params when building statements for polygon
- add tikz externalization to build process
- add a bunch of texsoup utils
- fix a few issues

## 0.22.2 (2025-12-27)

### Fix

- add -p variant for --profile
- have a global profile flag to control which profile is used
- add custom time controls for stress tests
- consolidate limits profile function
- fix a few type findings
- check preset version first thing in rbx
- add a few predownloaded assets to rbx to improve usability in a no-connection scenario
- add solution tags
- tell current profile TL in rbx time
- show a issue when solution is producing too much stderr
- fix method import
- teach user how to bypass version constraint in preset error
- warn on duplicate generator calls in testplan
- add duplicate call error to stress tests
- show errors when certain commands do not exist
- add vars to high-level problem context

### Refactor

- fix casing of variables

## 0.22.1 (2025-12-21)

### Fix

- fix remaining tests
- fix a couple weird tests
- fix a failing test in generator scripts
- fix a few generator script tests

## 0.22.0 (2025-12-21)

### Feat

- add inheritance to problem statements

### Fix

- add titles to contests
- inheriting contest vars when using inheritFromContest
- fix expander tests
- fix rbxtex statements
- reorder polygon upload docs

## 0.21.4 (2025-12-19)

### Fix

- add validator to polygon upload

## 0.21.3 (2025-12-19)

### Fix

- ensure other manual tests are uploaded to polygon

## 0.21.2 (2025-12-17)

### Fix

- correctly upload polygon statement assets
- handle exceptions properly in thread pools during polygon upload
- always kill processes in pipe.c

## 0.21.1 (2025-12-01)

### Fix

- ensure interactive process are ordered and we track order of visit

## 0.21.0 (2025-11-27)

### Feat

- add output validators when building and validating
- **\**: create unit test parser
- add parser for testplan and testgroups

### Fix

- fix BOCA interactive run when code is not chrooted
- read explanation files from tex accompanying samples
- add parsing for testplan:line tests
- print what solution is being used to generate outputs
- add unit tests new parsing
- fix parsing issues with input blocks
- be more lenient with whitespaces in unit parser
- fix whitespace normalization within input blocks in parsers
- add expectation support in unit test parser
- add support for bracket delimited input/output
- support @input in statement
- structure generation input coming from testplans
- smart delete solution in polygon
- save generator scripts in polygon uplaod
- use correct language in validator
- upload polygon solutions with correct lang
- upload statement resources in parallel
- parallelize solution uplaod to polygon
- fix image names in statement resources when uploading to polygon

## 0.20.1rc6 (2025-11-08)

### Fix

- add upload filtering for polygon

## 0.20.1rc5 (2025-11-08)

### Fix

- fix polygon schema
- add keybind based filters
- add small fetch optimization
- add sentinel for failures
- show loading box while loading code
- add fixes to boca view

## 0.20.1rc4 (2025-11-07)

### Fix

- ensure view refreshes do not deselected things
- pause refresh with zero
- ui friendly magenta

### Refactor

- \remove unused code

## 0.20.1rc3 (2025-11-07)

### Fix

- fix compilation error in scraping

## 0.20.1rc2 (2025-11-07)

### Fix

- improve width size

## 0.20.1rc1 (2025-11-07)

### Fix

- add substring team filter
- select code and show on row highligh

## 0.20.1rc0 (2025-11-07)

### Fix

- deal with small diffs
- add two types of diffs
- prefetch solutions in boca scraper view
- vibe code a boca view
- add code review for remote boca run

## 0.20.0 (2025-11-07)

### Fix

- fix boca scraper for remote download runs
- fix no caching of remote solutions
- add empty statement in BOCA when one is not present
- ensure builtin checker is read when path does not exist
- change > to >= when checking for TL when printing operator along with the time
- ensure AC testcases with warnings are render by live run reporter
- make compiled file relative to package

## 0.20.0rc11 (2025-11-06)

### Fix

- fix relpath walk up

## 0.20.0rc10 (2025-11-04)

### Fix

- fix a few typing errors
- fix function in rbx_ui
- schedule hard kill if program does not finish fast enough after interrupt
- fix hanging 0 testcase

## 0.20.0rc9 (2025-11-04)

### Fix

- handle ctrl+C in stress tests
- handle ctrl+C through a try-catch block
- make paths relative in irun
- ensure ctrl+C does not show stacktrace

## 0.20.0rc8 (2025-11-04)

### Fix

- optimize detailed table

## 0.20.0rc7 (2025-11-04)

### Fix

- fix issues with typing
- fix timing per language
- fix solution href in compilation error

## 0.20.0rc6 (2025-11-03)

### Fix

- reintroduce OK to rbx run
- add TL in timing summary and color appropriately things that should be info

## 0.20.0rc5 (2025-11-03)

### Fix

- add hilite
- split good and pass in timing summary

## 0.20.0rc4 (2025-11-03)

### Fix

- put rbx irun back in a state similar to rbx run
- ensure issues stack rule is printed as red
- ensure "slow" is printed as a TLE verdict
- print number of testcases in each group

## 0.20.0rc3 (2025-11-03)

### Fix

- use red background for failed
- use relative runs folder in solution header
- fix prerelease script

## 0.20.0rc2 (2025-11-03)

### Fix

- update packaging module

## 0.20.0rc1 (2025-11-03)

### Fix

- fix semver

## 0.20.0rc0 (2025-11-03)

### Feat

- colorize solutions with href
- add live run reporter

### Fix

- disable typer autocompletion
- show test metadata when testcase fails the validation
- fix checker compilation error
- fix duplicate parameter -o in irun
- handle kbi in ask commands in rbx time

## 0.19.11 (2025-10-21)

### Fix

- fix compilation issue with stress tests

## 0.19.10 (2025-10-17)

### Fix

- passes through all validators in one off commands

## 0.19.9 (2025-10-17)

### Fix

- run all validators

## 0.19.8 (2025-10-14)

### Fix

- fix GenerationMetadata for @copy entries

## 0.19.7 (2025-10-14)

### Fix

- add overrides for pypy compilation

## 0.19.6 (2025-10-14)

### Fix

- few cosmetic fixes

## 0.19.5 (2025-10-14)

### Fix

- show a nice error when editor is not found

## 0.19.4 (2025-10-11)

### Fix

- add mode to checker to support custom BOCA checkers

## 0.19.3 (2025-10-09)

### Fix

- ensure boca language utils honor env language finding per extension
- add support for additional extensions in languages
- ensure .limits folder is not created when reading limits file

## 0.19.2 (2025-10-09)

### Fix

- add configuration for fallback checker to match box behavior

### Refactor

- use get_checker_or_nil functions to check for main checker

## 0.19.1 (2025-10-08)

### Fix

- add extraValidators globally
- add glob support for extraValidators
- refactor get_globbed_code_items
- fix f-string quoting
- support adding stress findings to box testplans
- make sure stress tests add generatorScript.path to the yml
- only use generators with a matching extension/language
- add custom build dirs to presets

## 0.19.0 (2025-10-08)

### Feat

- add box testplan format
- add @copy to generator scripts
- add beta wizard backkend

### Fix

- use builtin checkers automagically
- use generator script root only for generators
- fix lookup by extension
- fix sanitization in irun
- cache transiently when sanitization is enabled
- use line flush when building samples
- add warning that wizard was vibe coded
- fix model routing
- fix default value for strategy

## 0.18.12 (2025-09-12)

### Fix

- support round in safeeval

## 0.18.11 (2025-09-12)

### Fix

- add --auto flag for rbx time

## 0.18.10 (2025-09-12)

### Fix

- show tls for BOCA packaging

## 0.18.9 (2025-09-12)

### Fix

- fix issue with limit modifiers
- use safeeval for timing formulae
- use safeeval for commands
- add safeeval for file mapping

## 0.18.8 (2025-09-12)

### Fix

- rollback Java class detection logic in BOCA
- add ability to specify language when building boca package

## 0.18.7 (2025-09-11)

### Fix

- add pypy3 support to boca

## 0.18.6 (2025-09-09)

### Fix

- skip invalid tests when generation fails in stress

## 0.18.5 (2025-09-09)

### Fix

- small fix on print error header

## 0.18.4 (2025-09-08)

### Fix

- dump statement build artifacts of contest into a dir
- ensure compilation errors are skipped in rbx run
- add option to skip invalid tests in stress
- invert order of teeing to make interactive merged output less flaky
- fix more tests

### Refactor

- small cosmetics changes

## 0.18.3 (2025-09-04)

### Fix

- fix several rbx/boca language integration issues

## 0.18.2 (2025-09-03)

### Fix

- fix default BOCA flags in env
- update preset to match all files

## 0.18.1 (2025-09-02)

### Fix

- fix statement matching

## 0.18.0 (2025-09-02)

### Feat

- support kotlin in boca
- add support for kotlin
- add support for envrc

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

## 0.26.0 (2026-02-22)

### Feat

- ensure polygon blocks come directly from statement building and preprocess+validate them
- add JSON serialization for MacroDefinitions
- add expand_macros with iterative hybrid TexSoup + text replacement
- add collect_macro_definitions with recursive file traversal
- add extract_definitions for parsing macro definitions from TeX
- add MacroDef and MacroDefinitions data model for demacro

### Fix

- ignore macros in tex->polygon transformation
- add support for macros block in default preset
- sync pre-commit ruff version with project and fix lint errors
- remove xdg-open command from wsl system (#385)

## 0.25.4 (2026-02-18)

### Fix

- update uv lock

## 0.25.3 (2026-02-18)

### Fix

- fix issue with ui visualizers

## 0.25.2 (2026-02-18)

### Fix

- limit to Python3.13 fort now
- fix event loop issue on Python3.14

## 0.25.1 (2026-02-18)

### Fix

- fix issue with visualizers and rbx ui
- prime template before rendering blocks
- use version range instead of exact major pin in upgrade command
- add dotenv loading
- fix a few extra tests and code
- migrate commitizen config

## 0.25.0 (2026-02-07)

### Feat

- migrate from poetry to uv

### Fix

- fix version provider for commitizen
- delete dangling svg
- Rename CLAUDE.md -> AGENTS.md
- remove poetry badge
- disable FMA on ARM
- show warning when not using rbx time
- dedup issue stack messages
- add issue severity markers
- handle typer.Exit() in rbx ui apps
- make rbx ui visible

## 0.24.0 (2026-02-01)

### Feat

- add visualizers

### Fix

- interactive mode docs
- add special code to visualizers
- add interactive to visualizers
- fall back to visualizer hwen no solution visualizer
- fully refactor visualizers
- add output_from to visualizers
- add ui visualizers
- fix novalidate typo
- add package size to packager

## 0.23.8 (2026-01-27)

### Fix

- fix packager statemment building
- improve build samples with sense of progress
- fixed output validation
- fix missing async

## 0.23.7 (2026-01-26)

### Fix

- fix inheritance bug
- fix stress test command
- show generator call along error
- add validate flags
- add --no-validate to irun

## 0.23.6 (2026-01-23)

### Fix

- fix fuzz tests
- small fix in error msg
- ensure output validators are also run for .out files

## 0.23.5 (2026-01-22)

### Fix

- warn about symlink issue with git-on-windows
- add bit to avoid building samples in statements
- show nice error messages about rbx version when parsing fails
- fix stats
- ensure clean can clean contests
- print better errors

## 0.23.4 (2026-01-19)

### Fix

- add check for .out output files
- build statement samples from generation entries, and handle .out and .ans separately
- add manual ans verification
- modify original sci function

## 0.23.3 (2026-01-17)

### Fix

- fix relative assets during contest statement building

## 0.23.2 (2026-01-17)

### Fix

- add --novalidate flag to commands
- add note that users can skip validation when building
- show error when summarization fails for problem within a contest

## 0.23.1 (2026-01-16)

### Fix

- improve rbx sum and add a detailed mode
- add rbx summary

## 0.23.0 (2026-01-10)

### Feat

- add fuzz tests to stresses

### Fix

- add group name to validator calls
- fix expected score validation
- add group deps to points problems
- add basic scoring implementation with a few todos
- slight refactor to accomodate for new scoring features
- skip invalid test cases in fuzz tests
- add .interaction file to docs
- add --slowest flag to stress tests
- add duplicate test check
- add polygon validation utils but dont use just yet
- fix contest statement expansion during inheritance
- add tikzpictures that are expanded into pdfs
- add externalization params when building statements for polygon
- add tikz externalization to build process
- add a bunch of texsoup utils
- fix a few issues

## 0.22.2 (2025-12-27)

### Fix

- add -p variant for --profile
- have a global profile flag to control which profile is used
- add custom time controls for stress tests
- consolidate limits profile function
- fix a few type findings
- check preset version first thing in rbx
- add a few predownloaded assets to rbx to improve usability in a no-connection scenario
- add solution tags
- tell current profile TL in rbx time
- show a issue when solution is producing too much stderr
- fix method import
- teach user how to bypass version constraint in preset error
- warn on duplicate generator calls in testplan
- add duplicate call error to stress tests
- show errors when certain commands do not exist
- add vars to high-level problem context

### Refactor

- fix casing of variables

## 0.22.1 (2025-12-21)

### Fix

- fix remaining tests
- fix a couple weird tests
- fix a failing test in generator scripts
- fix a few generator script tests

## 0.22.0 (2025-12-21)

### Feat

- add inheritance to problem statements

### Fix

- add titles to contests
- inheriting contest vars when using inheritFromContest
- fix expander tests
- fix rbxtex statements
- reorder polygon upload docs

## 0.21.4 (2025-12-19)

### Fix

- add validator to polygon upload

## 0.21.3 (2025-12-19)

### Fix

- ensure other manual tests are uploaded to polygon

## 0.21.2 (2025-12-17)

### Fix

- correctly upload polygon statement assets
- handle exceptions properly in thread pools during polygon upload
- always kill processes in pipe.c

## 0.21.1 (2025-12-01)

### Fix

- ensure interactive process are ordered and we track order of visit

## 0.21.0 (2025-11-27)

### Feat

- add output validators when building and validating
- **\**: create unit test parser
- add parser for testplan and testgroups

### Fix

- fix BOCA interactive run when code is not chrooted
- read explanation files from tex accompanying samples
- add parsing for testplan:line tests
- print what solution is being used to generate outputs
- add unit tests new parsing
- fix parsing issues with input blocks
- be more lenient with whitespaces in unit parser
- fix whitespace normalization within input blocks in parsers
- add expectation support in unit test parser
- add support for bracket delimited input/output
- support @input in statement
- structure generation input coming from testplans
- smart delete solution in polygon
- save generator scripts in polygon uplaod
- use correct language in validator
- upload polygon solutions with correct lang
- upload statement resources in parallel
- parallelize solution uplaod to polygon
- fix image names in statement resources when uploading to polygon

## 0.20.1rc6 (2025-11-08)

### Fix

- add upload filtering for polygon

## 0.20.1rc5 (2025-11-08)

### Fix

- fix polygon schema
- add keybind based filters
- add small fetch optimization
- add sentinel for failures
- show loading box while loading code
- add fixes to boca view

## 0.20.1rc4 (2025-11-07)

### Fix

- ensure view refreshes do not deselected things
- pause refresh with zero
- ui friendly magenta

### Refactor

- \remove unused code

## 0.20.1rc3 (2025-11-07)

### Fix

- fix compilation error in scraping

## 0.20.1rc2 (2025-11-07)

### Fix

- improve width size

## 0.20.1rc1 (2025-11-07)

### Fix

- add substring team filter
- select code and show on row highligh

## 0.20.1rc0 (2025-11-07)

### Fix

- deal with small diffs
- add two types of diffs
- prefetch solutions in boca scraper view
- vibe code a boca view
- add code review for remote boca run

## 0.20.0 (2025-11-07)

### Fix

- fix boca scraper for remote download runs
- fix no caching of remote solutions
- add empty statement in BOCA when one is not present
- ensure builtin checker is read when path does not exist
- change > to >= when checking for TL when printing operator along with the time
- ensure AC testcases with warnings are render by live run reporter
- make compiled file relative to package

## 0.20.0rc11 (2025-11-06)

### Fix

- fix relpath walk up

## 0.20.0rc10 (2025-11-04)

### Fix

- fix a few typing errors
- fix function in rbx_ui
- schedule hard kill if program does not finish fast enough after interrupt
- fix hanging 0 testcase

## 0.20.0rc9 (2025-11-04)

### Fix

- handle ctrl+C in stress tests
- handle ctrl+C through a try-catch block
- make paths relative in irun
- ensure ctrl+C does not show stacktrace

## 0.20.0rc8 (2025-11-04)

### Fix

- optimize detailed table

## 0.20.0rc7 (2025-11-04)

### Fix

- fix issues with typing
- fix timing per language
- fix solution href in compilation error

## 0.20.0rc6 (2025-11-03)

### Fix

- reintroduce OK to rbx run
- add TL in timing summary and color appropriately things that should be info

## 0.20.0rc5 (2025-11-03)

### Fix

- add hilite
- split good and pass in timing summary

## 0.20.0rc4 (2025-11-03)

### Fix

- put rbx irun back in a state similar to rbx run
- ensure issues stack rule is printed as red
- ensure "slow" is printed as a TLE verdict
- print number of testcases in each group

## 0.20.0rc3 (2025-11-03)

### Fix

- use red background for failed
- use relative runs folder in solution header
- fix prerelease script

## 0.20.0rc2 (2025-11-03)

### Fix

- update packaging module

## 0.20.0rc1 (2025-11-03)

### Fix

- fix semver

## 0.20.0rc0 (2025-11-03)

### Feat

- colorize solutions with href
- add live run reporter

### Fix

- disable typer autocompletion
- show test metadata when testcase fails the validation
- fix checker compilation error
- fix duplicate parameter -o in irun
- handle kbi in ask commands in rbx time

## 0.19.11 (2025-10-21)

### Fix

- fix compilation issue with stress tests

## 0.19.10 (2025-10-17)

### Fix

- passes through all validators in one off commands

## 0.19.9 (2025-10-17)

### Fix

- run all validators

## 0.19.8 (2025-10-14)

### Fix

- fix GenerationMetadata for @copy entries

## 0.19.7 (2025-10-14)

### Fix

- add overrides for pypy compilation

## 0.19.6 (2025-10-14)

### Fix

- few cosmetic fixes

## 0.19.5 (2025-10-14)

### Fix

- show a nice error when editor is not found

## 0.19.4 (2025-10-11)

### Fix

- add mode to checker to support custom BOCA checkers

## 0.19.3 (2025-10-09)

### Fix

- ensure boca language utils honor env language finding per extension
- add support for additional extensions in languages
- ensure .limits folder is not created when reading limits file

## 0.19.2 (2025-10-09)

### Fix

- add configuration for fallback checker to match box behavior

### Refactor

- use get_checker_or_nil functions to check for main checker

## 0.19.1 (2025-10-08)

### Fix

- add extraValidators globally
- add glob support for extraValidators
- refactor get_globbed_code_items
- fix f-string quoting
- support adding stress findings to box testplans
- make sure stress tests add generatorScript.path to the yml
- only use generators with a matching extension/language
- add custom build dirs to presets

## 0.19.0 (2025-10-08)

### Feat

- add box testplan format
- add @copy to generator scripts
- add beta wizard backkend

### Fix

- use builtin checkers automagically
- use generator script root only for generators
- fix lookup by extension
- fix sanitization in irun
- cache transiently when sanitization is enabled
- use line flush when building samples
- add warning that wizard was vibe coded
- fix model routing
- fix default value for strategy

## 0.18.12 (2025-09-12)

### Fix

- support round in safeeval

## 0.18.11 (2025-09-12)

### Fix

- add --auto flag for rbx time

## 0.18.10 (2025-09-12)

### Fix

- show tls for BOCA packaging

## 0.18.9 (2025-09-12)

### Fix

- fix issue with limit modifiers
- use safeeval for timing formulae
- use safeeval for commands
- add safeeval for file mapping

## 0.18.8 (2025-09-12)

### Fix

- rollback Java class detection logic in BOCA
- add ability to specify language when building boca package

## 0.18.7 (2025-09-11)

### Fix

- add pypy3 support to boca

## 0.18.6 (2025-09-09)

### Fix

- skip invalid tests when generation fails in stress

## 0.18.5 (2025-09-09)

### Fix

- small fix on print error header

## 0.18.4 (2025-09-08)

### Fix

- dump statement build artifacts of contest into a dir
- ensure compilation errors are skipped in rbx run
- add option to skip invalid tests in stress
- invert order of teeing to make interactive merged output less flaky
- fix more tests

### Refactor

- small cosmetics changes

## 0.18.3 (2025-09-04)

### Fix

- fix several rbx/boca language integration issues

## 0.18.2 (2025-09-03)

### Fix

- fix default BOCA flags in env
- update preset to match all files

## 0.18.1 (2025-09-02)

### Fix

- fix statement matching

## 0.18.0 (2025-09-02)

### Feat

- support kotlin in boca
- add support for kotlin
- add support for envrc

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

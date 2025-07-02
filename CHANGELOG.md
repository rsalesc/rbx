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

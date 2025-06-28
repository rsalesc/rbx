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

# Generators and `rbx.h`

`rbx` refuses to build a problem when a **generator** depends on `rbx.h`. This
page explains why and how to proceed if you really need to.

## Why this is an error

`rbx.h` exposes `getVar<T>("NAME")`, which reads the problem's
[variables](setters/variables.md) — your constraints — at compile time. That is
exactly what a **validator** wants. A **generator** is different: its job is to
produce a fixed, reproducible testset.

If a generator reads a constraint through `getVar`, then changing that constraint
silently changes every test the generator produces — with no edit to the
generator and no warning. A test that used to stress `N = 10^5` quietly becomes
`N = 10^6` (or shrinks), solutions that were once correctly judged may flip, and
nothing in your diff hints at why.

### Example

```cpp
// gen_max.cpp — DON'T: depends on a constraint
#include "rbx.h"
#include "testlib.h"

int main(int argc, char* argv[]) {
    registerGen(argc, argv, 1);
    int n = getVar<int>("MAX_N");   // <-- silent dependency on MAX_N
    println(n);
    return 0;
}
```

Bump `MAX_N` in `problem.rbx.yml` and this generator now emits a different test,
invisibly. Instead, pass the size explicitly as a generator argument so the
testset is pinned by your generator calls:

```cpp
// gen_max.cpp — DO: size comes from the call
#include "testlib.h"

int main(int argc, char* argv[]) {
    registerGen(argc, argv, 1);
    int n = atoi(argv[1]);          // value is fixed by the generator call
    println(n);
    return 0;
}
```

```yaml
# problem.rbx.yml — the size lives with the call, visible in your diff
generators:
  - name: "gen_max"
    path: "gen_max.cpp"
# ...
  - generator: { name: "gen_max", args: "100000" }
```

## Escape hatches

If you understand the trade-off and still want a generator to use `rbx.h`:

- **For a single generator**, add the suppression directive after the include:

  ```cpp
  #include "rbx.h"  // rbx-header-linter: disable
  ```

- **For the whole package**, remove `rbx-header` from the `cpp` language's
  `linters` list in your `env.rbx.yml`:

  ```yaml
  - name: "cpp"
    # ...
    linters: [testlib]   # rbx-header removed
  ```

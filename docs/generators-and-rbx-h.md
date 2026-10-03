# Generators and `rbx.h`

With the default environment, {{rbx}} refuses to build a problem when a **generator**
depends on `rbx.h`. This page explains why, and how to opt out.

## Why this is an error

`rbx.h` exposes `getVar<T>("NAME")`, which reads the problem's
[variables](setters/variables.md), your constraints, at compile time. This is useful in a
**validator**, which has to check those constraints. A **generator** is different: its job
is to produce a fixed, reproducible testset.

If a generator reads a constraint through `getVar`, changing that constraint also
changes every test the generator produces. A test that used to stress `N = 10^5`
becomes an `N = 10^6` test, and solutions that were judged correctly before may get a
different verdict. Your diff shows the constraint change, but not the tests that
changed with it.

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
although you didn't change the generator or its calls. Instead, pass the size
explicitly as a generator argument, so the testset is pinned by your generator calls:

```cpp
// gen_max.cpp — DO: size comes from the call
#include "testlib.h"

int main(int argc, char* argv[]) {
    registerGen(argc, argv, 1);
    int n = opt<int>(1);            // value is fixed by the generator call
    println(n);
    return 0;
}
```

```yaml
# problem.rbx.yml — the size lives with the call, visible in your diff
generators:
  - name: "gen_max"
    path: "gen_max.cpp"
testcases:
  - name: "secret"
    generators:
      - name: "gen_max"
        args: "100000"
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

# Generators

Generators are a {{testlib}} concept. They are programs that produce a testcase for a problem.

In this section, we'll learn how to write a generator. If you already know how to do so,
you can take a look at the [Testset section](index.md) to learn how to use them to produce
your testset.

## Generator call

In {{rbx}}, generators are programs that produce a testplan **from a given list of arguments**.

Let's say we have an executable `generator.exe`. Calling it should produce a testcase into the stdout.

```bash
./generator.exe 123 > testcase
```

The program + all the arguments passed to it constitute what we call a **generator call**.

In {{rbx}}, every generator should have a name. This name is used to identify the generator
within a generator call for a better readability. These names are defined in the `problem.rbx.yml`.

=== "problem.rbx.yml"

    ```yaml
    generators:
        - name: "generator"
          path: "generator.cpp"  
    ```


A valid generator call for the generator above would be `generator 123`.

## Idempotency

Generators should be idempotent. This means that two equal generator calls should always produce the same output.

{{testlib}} `rnd` library is designed to be used in an idempotent way. In fact, the seed number
for the `rnd` object's random number generator is a hash of the generator call.

This means that using the `rnd` object in a generator as the only source of randomness will
guarantee idempotency.

!!! tip "Introducing randomness"

    If you need to generate a testcase with the same set of parameters, but with a different seed,
    simply append a few random characters to the generator call.

    They will be ignored by your generator, but will be used to compute the seed for `rnd`,
    potentially producing a different testcase.

    ```
    gen 100
    gen 100 abc
    ```

    The two generator calls above will produce the same testcase for a generator expecting a single
    positional argument. The trailing `abc` piece is just used to produce a different seed.

## Writing a generator

You can read more about generators in the [testlib documentation](https://codeforces.com/blog/entry/18291).
It's very thorough and show a bunch of details about the APIs.

```cpp
#include "testlib.h"

int main(int argc, char* argv[]) {
    registerGen(argc, argv, 1);

    int N = opt<int>(1);
    int MAX = opt<int>("MAX");

    for (int i = 0; i < N; i++) {
      if (i) cout << " ";
      cout << rnd.next(1, MAX);
    }
    cout << endl;
}
```

The generator above produces a testcase with `N` integers, each one between 1 and `MAX`,
separated by spaces.

{{testlib}} provides the `opt<...>()` function to parse command line arguments, in two variants:

- `opt<>(int i)`: Parses a positional argument in the i-th position (1-indexed).
- `opt<>(string name)`: Parses argument with the given name.

In the case above, a valid generator call would be:

```bash
./generator.exe 10 --MAX_A=1000
```

To generate 10 random integers ranging from 1 to 1000.

Random numbers can be generated using the `rnd` object. The `rnd.next()` function can be used to generate a random integer between two values, but there are also other overrides available for it.

Take a look at the [testlib documentation](https://codeforces.com/blog/entry/18291) for more details, and
also at the examples on their [GitHub repository](https://github.com/MikeMirzayanov/testlib/tree/master/generators).

!!! info
    You can always call your generator manually with:

    ```bash
    rbx compile <path-to-generator>
    build/exe args...
    ```

    You can also run solutions interactively against a generator call with:

    ```bash
    rbx irun -g "<generator-name> <args...>"
    ```

    Read more about `rbx irun` in the [Running solutions](../running/index.md) section.

## Jngen, the jack of all trades

{{rbx}} also has a built-in integration with [jngen](https://github.com/ifsmirnov/jngen). This is a
test generation library implemented by Ivan Smirnov.

Jngen is a very powerful library that can generate all sorts of random objects: permutations, trees,
graphs, strings, and more.

It is a bit less mature and tested than {{testlib}}, but it's a great tool to have in your toolbox. Check it at [its GitHub repository](https://github.com/ifsmirnov/jngen).

To implement a Jngen-based generator, it suffices to include the `jngen.h` header

!!! danger "Under development"

    This section is under development. If you want to contribute, please
    send a PR to [our repository](https://github.com/rsalesc/rbx).

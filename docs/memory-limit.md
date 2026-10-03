# Memory limit

The memory limit of a problem is the `memoryLimit` you declare in `problem.rbx.yml`, in MiB.
{{rbx}} enforces it on every solution it runs, and on the interactor in interactive problems.
Checkers, validators and generators run under the environment's `defaultExecution` sandbox
limit instead.

```yaml title="problem.rbx.yml"
memoryLimit: 256  # 256 MiB
```

How that limit is *applied*, though, differs between operating systems, and you can see the
difference in the verdicts you get.

## How the limit is enforced

On **Linux**, {{rbx}} caps the program's address space with `RLIMIT_AS` -- the same thing
`ulimit -v` does -- set to exactly the memory limit. The cap is imposed by the kernel, so an
allocation past the limit *fails inside the program*: `malloc` returns null, `new` throws
`std::bad_alloc`, Python raises `MemoryError`.

On **macOS**, `RLIMIT_AS` is not imposed. Instead, {{rbx}} samples the program's resident memory
while it runs and kills it once it goes over the limit.

!!! warning
    The same solution can therefore get a **different verdict** on the two systems. A C++
    solution that allocates too much gets `RTE` on Linux, because a failed allocation crashes it,
    and `MLE` on macOS, because {{rbx}} killed it.

    A solution declared with `outcome: memory limit exceeded` will therefore fail on Linux. Use
    `outcome: mle+rte` instead, which accepts either and still rules out every other verdict:

    ```yaml title="problem.rbx.yml"
    solutions:
      - path: "sols/too-much-memory.cpp"
        outcome: mle+rte
    ```

!!! note
    On Linux the consequence goes further. Because `RLIMIT_AS` bounds the address space, a
    program's resident memory can never exceed the limit either. The watchdog has nothing left
    to catch, so **`MLE` is not a verdict you will see on Linux** for anything but a JVM
    language -- which is exempt from the cap, and whose `OutOfMemoryError` is an `RTE` anyway.

The Linux behavior is the one most online judges have, so it's the more faithful of the two.

## Reserved memory counts on Linux

`RLIMIT_AS` limits *virtual* memory -- everything the program maps, whether or not it ever touches
it. A program that reserves far more than it uses is charged for the reservation.

```cpp
int big[100'000'000];  // 400 MiB of .bss, never touched
```

Under a 256 MiB limit, this program will not even start on Linux, while on macOS it runs fine,
because the pages it never touches never become resident.

This is rarely a problem for solutions, which tend to use what they allocate. It matters for
*runtimes* that reserve a large arena up front, which is why the exemptions below exist.

## What is exempt

**Java and Kotlin.** The JVM refuses to start under an `RLIMIT_AS`, and it manages its own heap
anyway, so {{rbx}} drops the limit for JVM commands and passes the number to the JVM instead. That
is what `{memory}` is, in the run command of the bundled `env.rbx.yml`:

```yaml
command: "java -Xss100m -Xmx{memory}m -Xms{initialMemory}m -cp {executable} {javaClass}"
```

A Java solution that exceeds the limit therefore fails with an `OutOfMemoryError`, and gets `RTE`
on every system.

**Sanitized builds.** Sanitizers reserve enormous amounts of address space by design, so {{rbx}}
drops both the memory limit and the time limit when running a sanitized executable.

## Your machine's hard limit is a ceiling

Just like the [stack limit](stack-limit.md), the address-space limit has a hard ceiling that
{{rbx}} cannot exceed. If your hard limit is lower than the `memoryLimit` you asked for, programs
run with the *hard* limit -- a stricter one than you configured -- and {{rbx}} will point that out
at the end of any command that actually ran a program.

You can check it with `ulimit -v -H`, which reports the ceiling in KiB (`unlimited` is the usual,
and the good, answer). To raise it, open `/etc/security/limits.conf` and add:

```
* as soft unlimited
* as hard unlimited
```

!!! note
    A container memory cap (`docker --memory`) isn't an address-space limit. {{rbx}} can't see
    it, and a program over it is killed by the kernel.

## Compilation has its own limit

Compilers are memory-hungry, and on Linux they are capped too -- but by the `memoryLimit` of the
*compilation* sandbox, not by the problem's. It is set in your `env.rbx.yml`:

```yaml title="env.rbx.yml"
defaultCompilation:
  sandbox:
    memoryLimit: 1024 # 1 GiB
```

If a compilation starts failing with `virtual memory exhausted` after an upgrade -- heavy template
code and `#include <bits/stdc++.h>` both push this up -- raise that number. It is unrelated to the
memory limit of your problem, and raising it does not make solutions any more permissive.

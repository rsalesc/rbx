# Memory limit

The memory limit of a problem is the `memoryLimit` you declare in `problem.rbx.yml`, in MiB, and it
is the limit {{rbx}} enforces on every program it runs -- solutions, checkers, validators and
generators alike.

```yaml title="problem.rbx.yml"
memoryLimit: 256  # 256 MiB
```

How that limit is *applied*, though, differs between operating systems, and the difference is
visible in the verdicts you get. This page is about that difference.

## How the limit is enforced

On **Linux**, {{rbx}} caps the program's address space with `RLIMIT_AS` -- the same thing
`ulimit -v` does -- set to exactly the memory limit. The cap is imposed by the kernel, so an
allocation past the limit *fails inside the program*: `malloc` returns null, `new` throws
`std::bad_alloc`, Python raises `MemoryError`.

On **MacOS**, `RLIMIT_AS` is not imposed. Instead, {{rbx}} samples the program's resident memory
while it runs and kills it once it goes over the limit.

!!! warning
    This means the same solution can get a **different verdict** on the two systems. A C++ solution
    that allocates too much gets `RTE` on Linux, because it dies from a failed allocation, and
    `MLE` on MacOS, because {{rbx}} is the one that killed it.

    If you care about the verdict of a memory-hungry solution -- say you declared it with
    `outcome: memory limit exceeded` -- prefer `outcome: runtime error` or one of the
    [multi-outcome forms](setters/reference/package/index.md), so the expectation holds on both.

The Linux behavior is the one most online judges have, so it is the more faithful of the two. It
also has a consequence worth knowing about.

## Reserved memory counts on Linux

`RLIMIT_AS` limits *virtual* memory -- everything the program maps, whether or not it ever touches
it. A program that reserves far more than it uses is charged for the reservation.

```cpp
int big[100'000'000];  // 400 MiB of .bss, never touched
```

Under a 256 MiB limit, this program will not even start on Linux, while on MacOS it runs happily,
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

A Java solution that exceeds the limit therefore dies with an `OutOfMemoryError`, and gets `RTE`
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
    Containers are the common case where this bites. If you run {{rbx}} inside Docker with
    `--memory`, the container's own limit sits below anything you configure, and every program
    runs under it.

## Compilation has its own limit

Compilers are memory-hungry, and on Linux they are capped too -- but by the `memoryLimit` of the
*compilation* sandbox, not by the problem's. It lives in your `env.rbx.yml`:

```yaml title="env.rbx.yml"
defaultCompilation:
  sandbox:
    memoryLimit: 1024 # 1gb
```

If a compilation starts failing with `virtual memory exhausted` after an upgrade -- heavy template
code and `#include <bits/stdc++.h>` both push this up -- raise that number. It is unrelated to the
memory limit of your problem, and raising it does not make solutions any more permissive.

# Grading

In competitive programming, grading is the process of running and evaluating whether the participant's solution is correct for a given testcase (or a set of testcases).

{{rbx}} provides control over the full grading process, which in the case of setting problems,
is way simpler than in the case of running an actual contest.

In contests, the judging system is usually much more complex, and has to:

1. Give a fair verdict to the participant: TLE when the solution is too slow, WA when the solution is incorrect, etc.
2. Protect the system: prevent participants from cheating, crashing the server or making prohibited
  system calls.

!!! danger "Security"
    In the case of setting problems, we can focus on the first point, and assume setters are trusted
    actors and ignore the second one. Thus, {{rbx}} does not provide any mechanism to protect the system
    against malicious code being run. Be aware of that, and only run code written by authors you trust!

    Solutions will be run as the same user that ran the `rbx` command. If you want to be extra careful,
    you can run `rbx` inside a Docker container, or create an isolated user with limited permissions to
    run it.

## Running solutions

{{rbx}} runs solutions in a small Python sandbox. It sets CPU time, memory and output limits
with `setrlimit` (the call behind `ulimit`) and monitors resource usage while the program runs.

Unlike judging systems, where sandboxes are usually written in C/C++ and are run as privileged users, this sandbox is written in Python for better portability.

## Outcomes

Right after running the solution, we must give a verdict to it (or, as we call them in {{rbx}}, an outcome).

You can find the full list of outcomes in the table below.

| Outcome                   | Short name | Description                                                  |
| ------------------------- | ---------- | ------------------------------------------------------------ |
| `ACCEPTED`                | `AC`       | The solution produced a correct output.                      |
| `WRONG_ANSWER`            | `WA`       | The solution produced an incorrect output.                   |
| `TIME_LIMIT_EXCEEDED`     | `TLE`      | The solution took too much time to execute.                  |
| `MEMORY_LIMIT_EXCEEDED`   | `MLE`      | The solution used too much memory.                           |
| `IDLENESS_LIMIT_EXCEEDED` | `ILE`      | The solution was idle for too long.                          |
| `RUNTIME_ERROR`           | `RTE`      | The solution crashed.                                        |
| `OUTPUT_LIMIT_EXCEEDED`   | `OLE`      | The solution produced too much output.                       |
| `JUDGE_FAILED`            | `FL`       | The judge failed to execute or produced an incorrect answer. |
| `INTERNAL_ERROR`          | `IE`       | An internal error occurred.                                  |


All outcomes, except for `JUDGE_FAILED`, `WRONG_ANSWER` and `ACCEPTED`, are defined right after
the solution runs.

These three come from *checking*, a process that runs once the solution finishes. You can read
more about it in the [Checkers](checkers.md) section.

## Limits

The limits applied to a solution are defined in `problem.rbx.yml` under the `*limit` family of fields.

```yaml title="problem.rbx.yml"
# ... rest of the problem.rbx.yml ...
timeLimit: 1000  # 1 second
memoryLimit: 256  # 256 MB
```

Time is always defined in milliseconds, and memory is defined in megabytes. These limits are all
applied by the sandbox, and checked again once the solution exits.

!!! note
    The memory limit is applied differently on Linux and on macOS, and the difference shows up in
    the verdict a memory-hungry solution gets. See [Memory limit](../../memory-limit.md) for what
    to expect, and for the exemptions that apply to Java, Kotlin and sanitized builds.

You can also control the maximum size of the participant's output (which defaults to 4096 KB).

```yaml title="problem.rbx.yml"
# ... rest of the problem.rbx.yml ...
outputLimit: 1024  # 1024 KB
```

And you can also provide language-specific limits.

```yaml title="problem.rbx.yml"
# ... rest of the problem.rbx.yml ...
modifiers:
  java:
    time: 2000  # 2 second
    memory: 1024  # 1024 MB
```

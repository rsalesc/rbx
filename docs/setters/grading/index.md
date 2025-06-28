# Grading

In competitive programming, grading is the process of running and evaluating whether the participant's solution is correct for a given testcase (or a set of testcases).

{{rbx}} provides control over the full grading process, which in the case of setting problems,
is way simpler than in the case of running an actual contest.

In contests, the judging system is usually much more complex, and has to:

1. Give a fair verdict to the participant: TLE when the solution is too slow, WA when the solution is incorrect, etc.
2. Protect the system: prevent participants from cheating, from crashing the server, doing prohibited
  system calls, etc.

!!! danger "Security"
    In the case of setting problems, we can focus on the first point, and assume setters are trustful
    actors and ignore the second one. Thus, {{rbx}} does not provide any mechanism to protect the system
    against malicious code being run. Be aware of that, and only run code written by authors you trust!

    Solutions will be run as the same user that run the `rbx` command. If you want to be extra careful,
    you can run `rbx` inside a Docker container, or create an isolated user with limited permissions to
    run it.

## Running solutions

Solutions run through {{rbx}} are executed through a wrapper script. This script
applies memory and output limit constraints to the program through a mixture of `ulimit` calls
and realtime resource usage monitoring.

Different from judging systems, where sandboxes are usually written in C/C++ and are run as privileged users, this wrapper script is written in Python for better portability.

*If you're curious about the wrapper script, you can find it [here](https://github.com/rsalesc/rbx/blob/main/rbx/grading/judge/sandboxes/timeit.py).*

## Outcomes

Right after running the solution, we must give a verdict to it (or, as we call them in {{rbx}}, an outcome).

You can find the full list of outcomes in the table below.

| Outcome                   | Short name | Description                                                  |
| ------------------------- | ---------- | ------------------------------------------------------------ |
| `ACCEPTED`                | `AC`       | The solution passed all the testcases.                       |
| `WRONG_ANSWER`            | `WA`       | The solution produced an incorrect output.                   |
| `TIME_LIMIT_EXCEEDED`     | `TLE`      | The solution took too much time to execute.                  |
| `MEMORY_LIMIT_EXCEEDED`   | `MLE`      | The solution used too much memory.                           |
| `IDLENESS_LIMIT_EXCEEDED` | `ILE`      | The solution was idle for too long.                          |
| `RUNTIME_ERROR`           | `RTE`      | The solution crashed.                                        |
| `OUTPUT_LIMIT_EXCEEDED`   | `OLE`      | The solution produced too much output.                       |
| `JUDGE_FAILED`            | `FL`       | The judge failed to execute or produced an incorrect answer. |
| `INTERNAL_ERROR`          | `IE`       | An internal error occurred.                                  |


All outcomes, except for `JUDGE_FAILED`, `WRONG_ANSWER` and `ACCEPTED` are all defined right after
the solution runs.

There's a process that needs to be executed right after the solution runs, and it's called
checking, and you can read more about it in the [Checkers](checkers.md) section.

## Limits

All limits that are applied to a solution are defined in `problem.rbx.yml` under the `*limit` family of fields.

```yaml title="problem.rbx.yml"
# ... rest of the problem.rbx.yml ...
timeLimit: 1000  # 1 second
memoryLimit: 256  # 256 MB
```

Time is always defined in milliseconds, and memory is defined in megabytes. These limits are all
applied by the wrapper script, and checked further after the solution is executed.

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

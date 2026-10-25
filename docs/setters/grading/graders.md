# Graders

A grader is a program the problem setter writes and compiles together with every
solution. It owns `main()`: it reads the test and calls the functions the participant
wrote, then prints what they returned. Problems built this way are often called
**function-call problems**, and they're the standard format at the International
Olympiad in Informatics (IOI).

The participant never parses the input or prints the output. They only write a
function with a fixed signature. The problem is then about the algorithm rather than
about I/O, and the grader decides exactly what the participant's code receives.

In this section, we'll see how to declare a grader in {{rbx}} and how to write one,
how it changes the way checkers, interactors, and statements work, and how to give
the participants their copy of it and package the problem.

!!! note
    {{rbx}} supports graders written in C++ only, and solutions to a problem with a
    grader must also be in C++.

## Motivational problem

Let's assume we've got a problem that asks you to write the function below, which
must return the sum of the elements of `a`:

```cpp title="graders/sumgame.h"
#include <vector>

long long sum_all(std::vector<long long> a);
```

A test is a line with `n`, followed by a line with the `n` elements of `a`. The
participant submits a file defining `sum_all` and nothing else:

```cpp title="sols/main.cpp"
#include "sumgame.h"

long long sum_all(std::vector<long long> a) {
  long long s = 0;
  for (long long x : a) s += x;
  return s;
}
```

Notice the solution has no `main()`: the grader provides it.

## Declaring a grader

Point the `grader` field of your `problem.rbx.yml` at the grader's source:

```yaml title="problem.rbx.yml"
grader:
  path: graders/grader.cpp
```

From now on, {{rbx}} compiles every solution together with `graders/grader.cpp`. Like
judge systems, it keeps them in two separate translation units. The grader's directory is on
the include path. A solution finds `sumgame.h` there, the same way it would on a judge.

## Writing a grader

A grader is an ordinary C++ program, but it calls a few helpers from `rbx.h`:

```cpp title="graders/grader.cpp"
#include <cstdio>
#include <vector>

#include "rbx.h"
#include "sumgame.h"

int main() {
  rbx::grader::start(); // (1)!
  int n;
  std::scanf("%d", &n);
  std::vector<long long> a(n);
  for (auto &x : a) std::scanf("%lld", &x);
  rbx::grader::close_input(); // (2)!

  rbx::grader::before_call(); // (3)!
  long long result = sum_all(a);
  rbx::grader::after_call();

  std::printf("%lld\n", result);
}
```

1. Reads and checks the hidden header that {{rbx}} puts at the top of every test. More
   on it in [Reading the hidden header](#reading-the-hidden-header).
2. Closes `stdin`, so the participant's code can't read the rest of the input.
3. `before_call()` and `after_call()` frame the participant's call. Anything the
   participant prints to `stdout` lands between the two frames, and the checker turns
   it into a wrong answer.

Why the helpers? Your grader runs inside the same program as the participant's code,
so a careless solution could read the input before the grader does, or print an
answer of its own and exit. The helpers catch both, with the same tricks IOI graders
use.

!!! tip
    If the grader itself decides the answer is wrong (for example, the participant
    returned a value that breaks the rules), call
    `rbx::grader::verdict(rbx::grader::Verdict::WA, "message")` before `after_call()`.

Some of what a grader does is for the judge only, like that `verdict` check. Wrap
it in a `// BEGIN SECRET` and an `// END SECRET` line, so that the participants'
copy of the grader leaves it out (see
[Giving files to the participants](#giving-files-to-the-participants)):

```cpp title="graders/grader.cpp" hl_lines="2 6"
  long long result = sum_all(a);
  // BEGIN SECRET
  if (result == -1) {
    rbx::grader::verdict(rbx::grader::Verdict::WA, "sum_all gave up");
  }
  // END SECRET
  rbx::grader::after_call();
```

## Reading the hidden header

{{rbx}} sends every test of a problem with a grader to the judges with two extra lines on top:

```text
<a secret token>
<the name of the test's group>
<the input, unchanged>
```

`rbx::grader::start()` consumes them. The secret catches participant code that read
`stdin` first. The group name is what makes the header useful beyond security:
`rbx::getGroup()` returns it, and with it every
[per-group variable](../verification/validators.md#varying-constraints-per-test-group)
resolves correctly inside the grader, the checker and the interactor, **on every
judge**, not only when {{rbx}} runs them.

Your generators and validators never see the header. {{rbx}} adds it only where a
judge would read it. The files you write, and the statement, keep the plain input.
An input with no group of its own, such as a custom input for `rbx run` or a stress
test, gets an empty group name, so `getVar` returns the package-level values there.

!!! info
    {{rbx}} derives the secret from the package's `.rbx-id` file and generates it into
    `rbx.h`. {{rbx}} keeps it out of every file the participants receive. Keep
    `.rbx-id` with the package (commit it), or a package built elsewhere gets
    different secrets than the tests already uploaded to a judge.

!!! warning "The secrets are a tripwire"
    The secrets live in the same program as the participant's code, and the judge
    compiles that code next to the grader. A participant determined to cheat can
    read them, as with any IOI-style grader. They stop mistakes and casual attempts,
    and anything a participant must never see belongs in an
    [interactor](interactors.md), which runs as a separate program.

## Writing checkers and interactors

Let's make the problem a bit more interesting: in one subtask, an answer within 10
of the sum is good enough. We declare that tolerance as a variable, and override it
in that subtask's group:

```yaml title="problem.rbx.yml"
vars:
  TOL: 0

testcases:
  - name: approx
    vars:
      TOL: 10
    # ...
  - name: exact
    # ...
```

The checker of a problem with a grader reads the test with its header and the
grader's output with its frames, so it registers itself with a helper instead of
`registerTestlibCmd`:

```cpp title="checker.cpp" hl_lines="5 6"
#include "testlib.h"
#include "rbx.h"

int main(int argc, char *argv[]) {
  rbx::registerGraderChecker(argc, argv);
  long long tol = getVar<long long>("TOL");
  long long expected = ans.readLong();
  long long got = ouf.readLong();
  if (std::llabs(expected - got) > tol) {
    quitf(_wa, "expected %lld, got %lld", expected, got);
  }
  quitf(_ok, "within %lld", tol);
}
```

Everything after the registration is plain {{testlib}}. Notice `TOL`: when a group
overrides it in its `vars`, `getVar` returns that group's value. That's how one
checker applies different rules in each subtask.

!!! warning
    Include `testlib.h` **before** `rbx.h`. The checker and interactor helpers are only
    defined when {{testlib}} is already there.

In an interactive problem, the grader is the **stub**: it turns the participant's
function calls into messages to your [interactor](interactors.md). The stub needs no
helpers, and the interactor registers itself with `rbx::registerGraderInteraction`
instead of `registerInteraction`. The problem's interactor can't set `legacy: true`: the
interactor judges the interaction on its own, with no checker after it.

## Showing samples in the statement

The answers {{rbx}} stores for the judges include the grader's frames, which you
wouldn't want in a statement. So, for each sample of a batch problem, {{rbx}} also runs
the main solution with the grader's helpers turned off, and the statement shows that
plain answer. If you write a `.out.statement` file for a sample yourself, it still wins.

!!! warning
    A hand-written `.out` next to a manual test is the **statement** answer of a
    problem with a grader, not the judge's. The judge answer always comes from
    running the main solution with the grader.

## Giving files to the participants

Participants need the task header and a grader to test their code locally. List
those files in `attachments`. When you package the problem (`rbx package ...`), {{rbx}}
packs them in `build/attachments/<name>.zip`, where `<name>` is the problem's `name`:

```yaml title="problem.rbx.yml"
attachments:
  - path: graders/grader.cpp
    public: true
  - path: graders/sumgame.h
  - path: graders/template.cpp
    name: sumgame.cpp
  - samples: examples
```

Here `graders/template.cpp` is a skeleton solution, shipped as `sumgame.cpp`.

`public: true` derives the participants' version of a grader. {{rbx}} removes every
`// BEGIN SECRET` block, and replaces `#include "rbx.h"` with a few lines where the
helpers stop checking or framing anything: `verdict()` only prints its message to
`stderr` and exits. The result leaks neither the secret nor your variables.

If a C++ compiler is installed and some attachment is `public`, {{rbx}} compiles every
C++ source in the archive on
its own while packaging. It fails if one still needs something only the judge has,
such as `getVar`.

`samples: examples` adds every sample to the archive, as `examples/01.in` and
`examples/01.out`.

## Packaging a problem with a grader

You can package a problem with a grader for [Polygon](../packaging/polygon.md)
(`rbx package polygon`) and for [CMS](../packaging/cms.md)
(`rbx package polygon --cms`). Packaging for any other judge fails before {{rbx}}
builds anything.

- Polygon receives the grader as a resource compiled together with every solution,
  and the tests with their hidden header. When uploading, {{rbx}} uploads the tests as
  files and skips the validator, since Polygon would run it on the header.
  Polygon packages can't hold attachments, so add the archive to the problem by hand.
- CMS receives the grader, its headers and `rbx.h`, and the archive as a task
  attachment. CMS only makes `.h` headers available when it compiles a submission,
  so packaging fails if the grader depends on any other file.

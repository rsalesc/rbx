# Scoring

Scoring is how {{rbx}} turns the verdicts a solution got into the score it gets for the problem.

By default, a problem is scored ICPC-style: a solution either solves it or doesn't, and one
failed test is enough to reject it. That's not how every contest works. In an IOI-style problem,
a solution that only handles the small cases should still take home the points for them, and a
checker may even pay part of a test's points for an answer that is good but not the best.

In the sections below, we'll score a problem by points, split it into subtasks, and award partial
points from the checker.

## Motivational problem

Let's reuse the shortest-path problem from the [Checkers](checkers.md#output-answer-case)
section: find the **shortest** path between the vertices 1 and `N` of a graph. We'll split its
tests into two subtasks:

- `small`, worth 30 points, where `N` is at most 10;
- `large`, worth 70 points, with no further restriction.

A brute force that tries every path solves `small`, but `large` needs a proper search.

## Scoring by points

Let's tell {{rbx}} the problem is scored by points, and give each test group its `score`:

```yaml title="problem.rbx.yml"
# ... rest of the problem.rbx.yml ...
scoring: points # (1)!
testcases:
  - name: samples # (2)!
    testcaseGlob: statement/samples/*.in
  - name: small
    score: 30
    generatorScript:
      path: testplan/small.txt
  - name: large
    score: 70
    generatorScript:
      path: testplan/large.txt
```

1.  The default is `binary`, the ICPC-style scoring.
2.  A group without a `score` is worth 0 points, which is usually what you want for the samples.

A group pays its `score` only when **every** one of its tests passes. One failed test in `small`
and the solution gets nothing for it, however many other tests it passed. That's why each group
is usually a subtask.

!!! tip
    Subtasks usually differ only in their constraints. See
    [Varying constraints per test group](../verification/validators.md#varying-constraints-per-test-group)
    for how to have the validator check `N` is at most 10 in `small` only.

## Expecting a score

A solution that solves only one of the subtasks is neither {{tags.accepted}} nor
{{tags.wrong_answer}} everywhere, so let's tell {{rbx}} exactly what we expect from it. Pin its
points with `score`:

```yaml title="problem.rbx.yml"
solutions:
  - path: sols/main.cpp
    outcome: accepted
  - path: sols/brute.cpp
    outcome: incorrect # (1)!
    score: 30 # (2)!
```

1.  The brute force fails some tests in `large`, so it isn't `accepted`.
2.  It should score exactly the 30 points of `small`. A range, like `[20, 40]`, also works.

`rbx run` shows the points each group scored, and fails a solution whose total doesn't match its
`score`.

## Depending on other groups

Think of a solution that fails a test in `small` but somehow passes all of `large`. That's a bit
fishy, right? Let's make `large` **depend** on `small`:

```yaml title="problem.rbx.yml" hl_lines="9"
# ... rest of the problem.rbx.yml ...
testcases:
  - name: samples
    testcaseGlob: statement/samples/*.in
  - name: small
    score: 30
  - name: large
    score: 70
    deps: [small]
```

Now `large` only pays its points when all of `small`'s tests pass, so the fishy solution scores 0
there. If `small` depended on another group in turn, `large` would depend on that one too.

`scoring` can also be a mapping, and its `dependencies` key adds the two most common patterns for
you, on top of the `deps` each group declares:

- `samples`: every group depends on `samples`, so a solution that fails a sample scores 0.
- `ladder`: every group depends on the one declared before it, and the first one on `samples`.
  A group then only pays when every group declared before it passed.

```yaml title="problem.rbx.yml"
scoring:
  dependencies: ladder
```

The default, `manual`, doesn't add any: only the `deps` you declare count. In fact, `scoring: points`
is this same mapping, with every default.

## Awarding partial points

So far, a test either pays its points or doesn't. Some problems want something in between. Let's
give our problem a twist: a path *longer* than the jury's should still get some of the points,
more of them the closer its length is to the jury's.

A {{testlib}} checker awards part of a test's points with `quitp`. {{rbx}} reads its value as a
**percentage** of the test's points, between 0 and 100:

```cpp title="checker.cpp"
// ... the checker from the Checkers section, but without rejecting a longer path ...
ans.quitif(psize < jsize, _wa,
           "participant's path is shorter than the jury's path (size %d < %d)",
           psize, jsize);
if (psize > jsize) {
    quitp(100.0 * jsize / psize, "path with %d vertices, the jury's has %d", psize, jsize);
}
ouf.quitf(_ok, "path with %d vertices found", K);
```

This checker pays 50% of the test's points for a path twice as long as the jury's. `quitp(100)`
is an {{tags.accepted}}, `quitp(0)` a {{tags.wrong_answer}}, and anything in between is a
*partially correct* verdict.

How does that become the group's points? The group pays its `score` times its **lowest** test
score: 90% of its points when every test scored 90%, and nothing when one test failed. That's
the rule we've used all along, since a test that passes scores 100% and one that fails scores 0%.

Dependencies keep working the same way, too: no test in a group scores more than the lowest test
score among the groups it depends on.

## Summing test scores

Paying for the lowest test is the usual way to score a subtask. Sometimes, though, you want each
test to count on its own: think of an optimization problem, where every test is worth the same
and a solution collects whatever it scores on each.

That's what a group's `aggregation` controls. It defaults to `min`, the lowest-test rule we've
seen so far. With `sum`, the group splits its `score` evenly across its tests, and each test pays
its share times its own score:

```yaml title="problem.rbx.yml"
# ... rest of the problem.rbx.yml ...
scoring:
  aggregation: min # (1)!
testcases:
  - name: small
    score: 30
  - name: large
    score: 70
    aggregation: sum # (2)!
```

1.  `min` is the default, so this line doesn't change anything.
2.  Only `large` uses `sum`.

With 10 tests in `large`, each test is worth 7 points, so a test scoring 50% pays 3.5 of them.
Meanwhile, `small` still pays nothing unless all of its tests pass.

## Expecting partial scores

Last but not least, tell {{rbx}} which solutions you expect to score partially. Declare them
`partially correct`, and pin their points with `score`:

```yaml title="problem.rbx.yml"
solutions:
  - path: sols/longer-path.cpp
    outcome: partially correct
    score: 75
```

Every test such a solution doesn't pass must be partially correct. A solution that also gets a
{{tags.wrong_answer}} is `incorrect`, and its `score` still pins its points.

`rbx run` marks each partially correct test with `~`, followed by the percentage it scored.

You can read about every scoring field in the [`problem.rbx.yml` reference](/setters/reference/package).

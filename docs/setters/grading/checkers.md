# Checkers

Checker is a concept introduced by {{testlib}} to verify whether the participant's solution is correct for a given testcase.

A checking algorithm can range from a very simple diff between two files, to a much more complex algorithm such as "does the participant output contains a *path* between two specific vertices by using
edges that are part of the input graph?".

We **strongly** recommend using {{testlib}} checkers for your problems, as they are battle-tested and
will cover most of your needs. Also, they're usually lenient with extra spaces, newlines and such.

Think of all the frustration you had in your life with presentation errors and problems that asked
you to print the "minimum lexicographically path in a graph" just to force the solution to be unique. {{testlib}} checkers are here to solve that.

!!! danger "Non-{{testlib}} checkers"
    **Please**, use {{testlib}} checkers. {{rbx}} is seriously opinionated about this, and although
    it will most of the times work with non-{{testlib}} checkers, no guarantees are given.

    This document will intentionally not cover non-{{testlib}} checkers.

## Built-in {{testlib}} checkers

{{rbx}} provides out-of-the-box support for the built-in {{testlib}} checkers defined [here](https://github.com/MikeMirzayanov/testlib/tree/master/checkers).

You can use them by specifying the `checker` field in your `problem.rbx.yml` file.

```yaml title="problem.rbx.yml"
# ... rest of the problem.rbx.yml ...
checker:
  - path: "wcmp.cpp"
```

{{rbx}} will automatically detect it is a built-in checker and will download it from the {{testlib}} repository.

The most common built-in checkers are described in the table below, but you should feel free to explore the others. The `wcmp.cpp` checker
is the default checker for {{rbx}}, since it's basically a space-tolerant diff.

+--------------+----------------------------------------------------------------------------------------------+
|   Checker    |                                         Description                                          |
+==============+==============================================================================================+
| `wcmp.cpp`   | Compares the *sequence of words* of two files, as if they were a tuple.                      |
|              | First, the files are tokenized, and then each token is compared.                             |
+--------------+----------------------------------------------------------------------------------------------+
| `ncmp.cpp`   | Same as `wcmp.cpp`, but compares 64-bit signed integers.                                     |
+--------------+----------------------------------------------------------------------------------------------+
| `uncmp.cpp`  | Same as `ncmp.cpp`, but disregards the order of the numbers.                                 |
+--------------+----------------------------------------------------------------------------------------------+
| `yesno.cpp`  | Compares a single word which must be "YES" or "NO" (case-insensitive).                       |
+--------------+----------------------------------------------------------------------------------------------+
| `nyesno.cpp` | Same as to `wcmp.cpp`, but all tokens must be "YES" or "NO" (case-insensitive).              |
+--------------+----------------------------------------------------------------------------------------------+
| `dcmp.cpp`   | Compares two doubles by ensuring their maximal absolute or relative error is at most `1e-6`. |
+--------------+----------------------------------------------------------------------------------------------+
| `rcmp.cpp`   | Same as `dcmp.cpp`, but uses an error of `1e-9` instead.                                     |
+--------------+----------------------------------------------------------------------------------------------+

## Custom {{testlib}} checkers

You can also write your own {{testlib}} checkers. Checkers in {{rbx}} are programs that receives three arguments:

```bash
./checker <input_file> <output_file> <answer_file>
```

The arguments are:

- `<input_file>`: the input file for the testcase.
- `<output_file>`: the output file produced by the participant.
- `<answer_file>`: the answer file, i.e. the one that contains the output of the model solution.

Some times, the `<answer_file>` is not needed. Let's see a simple case first, and then let's look at one
where the `<answer_file>` is needed.

### Output-only case

Let's say we have a problem that asks you to find a path between two vertices 1 and `N` in a graph.

In this case, we want to check whether:

- The participant's output contains a *path* between two vertices 1 and `N` in the input graph.
- The path is simple, i.e. it doesn't visit any vertex (or edge) more than once.

Let's say the input is given in the following format:

```title="Input format"
N M
u_1 v_1
u_2 v_2
...
u_M v_M
```

And the output is printed in the following format:

```title="Output format"
K
p_1 p_2 ... p_K
```

Where `K` is the number of vertices in the path, and `p_1 p_2 ... p_K` is the sequence of vertices in the path.

We can write a checker that does exactly that.

=== "checker.cpp"

    ```cpp linenums="1"
    #include "testlib.h"

    int main(int argc, char *argv[]) {
        registerTestlibCmd(argc, argv);

        // `inf` is a stream used to read the input file.
        int N = inf.readInt();
        int M = inf.readInt();
        
        vector<set<int>> adj(N + 1);
        for (int i = 0; i < M; i++) {
            int u = inf.readInt();
            int v = inf.readInt();
            adj[u].insert(v);
            adj[v].insert(u);
        }

        // Read the participant's output
        // `ouf` is a stream used to read the participant's output.
        int K = ouf.readInt(1, N, "path size"); // (1)!
        vector<int> path(K);
        for (int i = 0; i < K; i++) {
            path[i] = ouf.readInt(1, N, "path vertex");
        }

        // Check if the path starts at 1 and ends at N.
        ouf.quitif(path[0] != 1, _wa, "path does not start at 1");  // (2)!
        ouf.quitif(path[K - 1] != N, _wa, "path does not end at N");

        // Check if the path is simple
        set<int> seen;
        for (int i = 0; i < K; i++) {
            ouf.quitif(seen.count(path[i]), _wa, "path is not simple");
            seen.insert(path[i]);
        }
        
        ouf.quitf(_ok, "path with %d vertices found", K);  // (3)!
    }
    ```

    1.  Notice how we're strict with the bounds of the numbers we're reading from the user. If the user
        provides an invalid number, we'll mark the participant's output as wrong.

        This is especially important here, not only for correctness, but also because we'll allocate
        a vector of size `N` in the next step, and we don't want the participant to provide an invalid
        number.

    2.  We use `quitif` to immediately stop the program and mark the participant's output as wrong when
        some condition is not met.

        One can also use the `quitf` variant to simply quit. This allows one to write an equivalent code:

        ```cpp
        if (condition_is_not_met) {
          ouf.quitf(_wa, "...");
        }
        ```

    3.  We use `quitf(_ok, ...)` to mark the participant's output as correct, and notice we can use
        format specifiers in the message.

=== "problem.rbx.yml"

    ```yaml
    # ... rest of the problem.rbx.yml ...
    checker:
      - path: "checker.cpp"
    ```

Notice checking only the participant's output here was more than enough. We don't need to consume the `<answer_file>`
at all.

You can learn more about {{testlib}} streams and all the functions available in their [official documentation](https://codeforces.com/blog/entry/18431).

### Output + answer case

Sometimes, it's also important to consider the jury's solution.

Let's consider the following modification to the problem above: now, you have to find the **shortest** path between two vertices 1 and `N`. We can assume the input and output format stays the same.

The only way to be sure the participant's solution is the shortest possible is to actually
find the shortest path in the input graph. That is exactly what our model solution already does, right? We
could proceed in two ways here:

1. :warning: We could simply read the answer from the `<answer_file>` and ensure the participant's path size is equals to
the jury's path size, and otherwise mark the participant's output as wrong.

2. :white_check_mark: We could compare the participant's path with the jury's path, and if they are different, mark the participant's output as wrong if it's longer than the jury's path, **or mark the jury's output as wrong if it's longer than the participant's path.**

(1) is very dangerous for obvious reasons: what if the jury's solution is wrong? Of course, for shortest paths we simply know
the optimal solution is a BFS, and it's hard to get that wrong, right? But think of more complex problems which are totally new
and that probably have never been solved before. It's very easy to get that wrong, and having a checker for that can help detecting
an issue in setting time (or, in worst case, in contest time).

(2) is the way to go here, as it ensures that the participant's solution is at least as good as the jury's solution. {{rbx}} has
a special outcome called `JUDGE_FAILED`, which is used to convey a checking failure, when the jury's output is wrong.

=== "checker.cpp"

    ```cpp linenums="1" hl_lines="5-26 51-60"
    #include "testlib.h"
    // Reads a path from the given stream, ensures it's valid
    // according to `N` and `adj`, and returns its size.
    // (1)!
    int readPath(InStream &stream,
                 int N,
                 const vector<set<int>> &adj) {
      int K = stream.readInt(1, N, "path size");
      vector<int> path(K);
      for (int i = 0; i < K; i++) {
        path[i] = stream.readInt(1, N, "path vertex");
      }

      // Check if the path starts at 1 and ends at N.
      stream.quitif(path[0] != 1, _wa, "path does not start at 1");
      stream.quitif(path[K - 1] != N, _wa, "path does not end at N");

      // Check if the path is simple
      set<int> seen;
      for (int i = 0; i < K; i++) {
        stream.quitif(seen.count(path[i]), _wa, "path is not simple");
        seen.insert(path[i]);
      }

      return K;
    }

    int main(int argc, char *argv[]) {
        registerTestlibCmd(argc, argv);

        // `inf` is a stream used to read the input file.
        int N = inf.readInt();
        int M = inf.readInt();
        
        vector<set<int>> adj(N + 1);
        for (int i = 0; i < M; i++) {
            int u = inf.readInt();
            int v = inf.readInt();
            adj[u].insert(v);
            adj[v].insert(u);
        }

        // Read the participant's output
        // `ouf` is a stream used to read the participant's output.
        int K = ouf.readInt(1, N);
        vector<int> path(K);
        for (int i = 0; i < K; i++) {
            path[i] = ouf.readInt(1, N);
        }

        int psize = readPath(ouf, N, adj); // participant's path size
        int jsize = readPath(ans, N, adj); // jury's path size

        // Compare sizes of the paths (2)
        ouf.quitif(psize > jsize, _wa,
                   "participant's path is longer than the jury's path (size %d > %d)",
                   psize, jsize);
        ans.quitif(psize < jsize, _wa,
                   "participant's path is shorter than the jury's path (size %d < %d)",
                   psize, jsize);

        ouf.quitf(_ok, "path with %d vertices found", K);
    }
    ```
    
    1.  Notice how we extract the common logic of reading a path from a stream into a function.

        {{testlib}} is smart: if quitf is called with `_wa`, it will mark the corresponding stream as wrong,
        resulting in a WA verdict if the participant's output is wrong, and in a JUDGE_FAILED verdict if the
        jury's output is wrong.

    2.  We use `_wa` to mark the jury's output (represented by the `ans` stream) as wrong and cause a JUDGE_FAILED verdict.

        We could as well use `quitif(..., _fail, ...)`, which would have the same effect.

        !!! note
            `_fail` conveys a checking failure, regardless of the stream it was applied to.

            `_wa` conveys a wrong answer, and is applied to the stream that was being checked.

=== "problem.rbx.yml"

    ```yaml
    # ... rest of the problem.rbx.yml ...
    checker:
      - path: "checker.cpp"
    ```

Notice how we read from both outputs, validating each of them individually, and compare their sizes at the end, giving
an appropriate verdict for each of them, and avoiding assuming the jury's output is 100% correct.

You can learn more about {{testlib}} streams and all the functions available in their [official documentation](https://codeforces.com/blog/entry/18431).
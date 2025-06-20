# Validators

Validator is a concept introduced by {{testlib}} to verify whether the tests you generate
for a problem are in the format you really expect.

Think of the frustrating scenarios where you've written in the statement that the graph should
be connected, or a tree, or a DAG, but there was a test in your testset that contradicted this.
Even experienced setters make these mistakes, and it's important to have extra guards to catch
them.

Similar to {{codeforces}}, {{rbx}} offers built-in support for {{testlib}} validators (and
also encourages you to use it), but also provides the flexibility for you to write your own.

## Motivational problem

For the next sections, let's assume we have a problem that asks you to find a path between two
vertices 1 and `N` in a **connected** graph with `N` vertices numbered from 1 to `N`, where `N`
is between 2 and 1000 and `M` is between 1 and `N * (N - 1) / 2`.

Let's assume the input is given like this:

```
3 2
1 2
2 3
```

In the first line, we have the number of vertices `N` and the number of edges `M`, separated by a single space.

In the next `M` lines, we have the edges of the graph, represented by two integers `u` and `v` separated by a single space,
indicating that there is an undirected edge between vertex `u` and vertex `v`. Then, the file ends.

Let's write a validator to verify that our testset
does not violate these constraints.

## Using {{testlib}} validators

*You can read more about {{testlib}} validators in the [Codeforces documentation](https://codeforces.com/blog/entry/18426).*

To use a {{testlib}} validator, you need to specify the path to the validator in the `validator` field.
{{testlib}} validators are always written in C++ and should include the `testlib.h` header. {{rbx}} treats
this header especially, and will automatically place it along your validator when compiling it.

```yaml title="problem.rbx.yml"
validator:
  path: 'validator.cpp'
```

Let's write a simple validator that checks the input format above.

```cpp title="validator.cpp" linenums="1"
#include "testlib.h"

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);

  int n = inf.readInt(2, 1000, "N"); // (1)!
  inf.readSpace();
  int m = inf.readInt(1, n * (n - 1) / 2, "M"); // (2)!
  inf.readEoln();

  // Read all the M edges of the graph.
  for (int i = 0; i < m; i++) {
    int u = inf.readInt(1, n, "u");
    inf.readSpace();
    int v = inf.readInt(1, n, "v");
    inf.readEoln();
  }

  inf.readEof(); // (3)!
}
```

1.  We read the number of vertices `N` and check that it is an integer between 2 and 1000.
    Notice we also set a variable name `N`.

    This is used for {{testlib}} to print useful error messages when an issue is found.

2.  We read the number of edges `M` and check that it is between 1 and `N * (N - 1) / 2`.
   
    Notice how we re-use the variable `n` we read before.

3.  We read the end of the file.


Notice we're super strict about spaces, end-of-lines and end-of-file here. That's the purpose
of the validator component.

Of course, we still have to check that the graph is connected, but let's do this in a minute.

Let's first talk about variables. As explained in the [Variables](variables.md) section,
we can use variables to refer to constraints in the input. 

At the moment, we're hard coding the lower and upper bounds for `N` in the validator. If we change the problem statement to, let's say,
allow `N` between 3 and 500 instead, we'd have to remember to modify the validator. This is a dangerous
practice, as it's super easy to forget to do so.

Let's do the following modifications to our problem to make it safer:

=== "validator.cpp"
    ```cpp hl_lines="2 6-7 9" linenums="1"
    #include "testlib.h"
    #include "rbx.h"

    int main(int argc, char *argv[]) {
      registerValidation(argc, argv);
      int MIN_N = getVar<int>("MIN_N");
      int MAX_N = getVar<int>("MAX_N");

      int n = inf.readInt(MIN_N, MAX_N, "N");
      // ...rest of the validator...
    }
    ```

=== "problem.rbx.yml"
    ```yaml
    # ...rest of the problem.rbx.yml...
    vars:
      MIN_N: 2
      MAX_N: 1000
    ```

{{rbx}} will automatically generate an `rbx.h` header file for you, which will include the variables
you defined in your `problem.rbx.yml` file, that you can access in your validator with the `getVar<>()` function.

To read more about variables, check the [Variables](variables.md) section.

Now, let's finally check that the graph is connected.

```cpp title="validator.cpp" hl_lines="4-29 41 50-51 54" linenums="1"
#include "testlib.h"
#include "rbx.h"

bool checkConnected(const vector<vector<int>> &adj, int n) {
  vector<bool> visited(n + 1);
  queue<int> q;
  q.push(1);
  visited[1] = true;

  while (!q.empty()) {
    int u = q.front();
    q.pop();

    for (int v : adj[u]) {
      if (!visited[v]) {
        visited[v] = true;
        q.push(v);
      }
    }
  }

  for (int i = 1; i <= n; i++) {
    if (!visited[i]) {
      return false;
    }
  }

  return true;
}

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);
  int MIN_N = getVar<int>("MIN_N");
  int MAX_N = getVar<int>("MAX_N");

  int n = inf.readInt(MIN_N, MAX_N, "N");
  inf.readSpace();
  int m = inf.readInt(1, n * (n - 1) / 2, "M");
  inf.readEoln();

  vector<vector<int>> adj(n + 1);

  // Read all the M edges of the graph.
  for (int i = 0; i < m; i++) {
    int u = inf.readInt(1, n, "u");
    inf.readSpace();
    int v = inf.readInt(1, n, "v");
    inf.readEoln();

    adj[u].push_back(v);
    adj[v].push_back(u);
  }

  ensuref(checkConnected(adj, n), "The graph is not connected.");

  inf.readEof();
}
```

!!! tip

    You can always manually call a validator on a custom input with `rbx validate`.

    {{ asciinema("i1qR2ygzbV7rYnd03uAQ1mPzb") }}

## Using custom validators

Let's say you want to build a custom Python3 validator. You can do that similarly by specifying a Python
validator in the `validator` field.

=== "problem.rbx.yml"
    ```yaml
    validator:
      path: 'validator.py'
    ```

=== "validator.py"
    ```python
    # ... read the input ...

    def check_connected(adj, n):
        # ... check if the graph is connected ...
    
    assert check_connected(adj, n), "The graph is not connected."
    
    # ...
    ```
    
!!! warning
    We strongly recommend using {{testlib}} validators.

    They're not only easier to write, but also provides a set of tested utilites to read and
    stricly check parts of the input, something you would've to do manually otherwise.


## Defining additional validators

{{rbx}} provides a couple ways of defining additional validators for a problem or testset.

The first one is by using the `extraValidators` field in the `problem.rbx.yml` file.

This allows you to, for instance, define validators that check for different properties of the input
separately.

```yaml title="problem.rbx.yml" hl_lines="3-10"
validator:
  path: 'validator.cpp'
extraValidators:
  - path: 'connected-validator.cpp'
  - path: 'bipartite-validator.cpp'
```

Or define validators that check for common properties of the input file that you'd rather keep off
of the main validator.

```yaml title="problem.rbx.yml" hl_lines="3-10"
validator:
  path: 'validator.cpp'
extraValidators:
  - path: 'only-printable-ascii.py'
  - path: 'no-tabs.py'
  - path: 'no-consecutive-spaces.py'
```

Another way of additional validators it to specify validators (or extra validators) for a specific test group in your problem.

This is often useful for problems that have multiple subtasks with different constraints, but can also be
useful for ICPC-style contests where you use the grouping feature to separate tests you've generated
with a specific purpose in mind.

Considering the problem above one more time, let's say we have a specific testplan focused on tests that contain a straight path from 1 to `N`, because we know that this
is the largest solution a participant can get. We might want to have a validator to ensure tests coming from this testplan
really have this property.

```yaml title="problem.rbx.yml" hl_lines="10-20"
# ... rest of the problem.rbx.yml ...
validator:
  path: 'validator.cpp'
testcases:
  - name: samples
    testcaseGlob: manual_tests/samples/*.in
  - name: general
    generatorScript:
      path: testplan/general.txt
  - name: straight
    generatorScript:
      path: testplan/straight.txt
    extraValidators:
      - path: 'straight-validator.cpp'
```










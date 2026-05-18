#include "testlib.h"
#include <bits/stdc++.h>

using namespace std;

int main(int argc, char *argv[]) {
  registerValidation(argc, argv);

  int n = inf.readInt(2, 1000, "n");
  inf.readEoln();

  vector<int> par(n + 1);
  for (int i = 1; i <= n; i++)
    par[i] = i;
  function<int(int)> find = [&](int x) {
    while (par[x] != x)
      x = par[x] = par[par[x]];
    return x;
  };

  for (int i = 0; i < n - 1; i++) {
    int u = inf.readInt(1, n, "u");
    inf.readSpace();
    int v = inf.readInt(1, n, "v");
    inf.readEoln();
    ensuref(u != v, "self loop at vertex %d", u);
    int ru = find(u), rv = find(v);
    ensuref(ru != rv, "edge (%d, %d) creates a cycle", u, v);
    par[ru] = rv;
  }

  int root = inf.readInt(1, n, "root");
  inf.readEoln();
  (void)root;

  inf.readEof();

  // Connectivity: all vertices share one component (it is a tree).
  int r = find(1);
  for (int i = 2; i <= n; i++)
    ensuref(find(i) == r, "the graph is not connected");
}

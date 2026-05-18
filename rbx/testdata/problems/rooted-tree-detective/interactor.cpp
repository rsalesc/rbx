#include "testlib.h"
#include <bits/stdc++.h>

using namespace std;

int main(int argc, char *argv[]) {
  registerInteraction(argc, argv);

  // Hidden input: n, then n-1 edges, then the hidden root.
  int n = inf.readInt(2, 1000, "n");
  vector<pair<int, int>> edges(n - 1);
  vector<vector<int>> adj(n + 1);
  for (int i = 0; i < n - 1; i++) {
    int u = inf.readInt(1, n, "u");
    int v = inf.readInt(1, n, "v");
    edges[i] = {u, v};
    adj[u].push_back(v);
    adj[v].push_back(u);
  }
  int root = inf.readInt(1, n, "root");

  // Compute subtree sizes and depths w.r.t. the hidden root.
  vector<int> sz(n + 1, 1), dep(n + 1, 0), par(n + 1, 0);
  vector<int> order;
  {
    vector<bool> vis(n + 1, false);
    queue<int> q;
    q.push(root);
    vis[root] = true;
    dep[root] = 0;
    par[root] = 0;
    while (!q.empty()) {
      int x = q.front();
      q.pop();
      order.push_back(x);
      for (int y : adj[x]) {
        if (!vis[y]) {
          vis[y] = true;
          dep[y] = dep[x] + 1;
          par[y] = x;
          q.push(y);
        }
      }
    }
  }
  for (int i = (int)order.size() - 1; i >= 0; i--) {
    int x = order[i];
    if (par[x] != 0)
      sz[par[x]] += sz[x];
  }

  // Preamble: the public structure spans several lines, followed by the
  // query budget. Only after this does the back-and-forth begin.
  int budget = 2 * n;
  cout << n << endl;
  for (auto &e : edges)
    cout << e.first << ' ' << e.second << endl;
  cout << budget << endl;
  cout << flush;

  int queries = 0;
  while (true) {
    string cmd = ouf.readToken("\\?|!", "command");
    if (cmd == "?") {
      int v = ouf.readInt(1, n, "v");
      queries++;
      if (queries > budget)
        quitf(_wa, "exceeded the query budget of %d queries", budget);
      // Each answer spans two lines: subtree size, then depth.
      cout << sz[v] << endl;
      cout << dep[v] << endl;
      cout << flush;
    } else {
      int r = ouf.readInt(1, n, "answer");
      if (r == root) {
        tout << queries << endl;
        quitf(_ok, "root %d found with %d queries", root, queries);
      } else {
        quitf(_wa, "reported root %d, but the real root is %d", r, root);
      }
    }
  }
}

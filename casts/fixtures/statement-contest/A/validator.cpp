#include "testlib.h"
#include "rbx.h"

// The docs snippet leans on testlib pulling `std` into scope; with GCC 15 it
// does not, so the fixture spells the dependency out.
#include <queue>
#include <vector>
using namespace std;

// The connected-graph validator from docs/setters/verification/validators.md.
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
  int MIN_N = getVar<int>("N.min");
  int MAX_N = getVar<int>("N.max");

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

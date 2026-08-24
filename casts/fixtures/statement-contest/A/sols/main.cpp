#include <algorithm>
#include <iostream>
#include <queue>
#include <vector>
using namespace std;

// BFS from 1 to N, printing the path length followed by the path itself.
int main() {
    int n, m;
    cin >> n >> m;
    vector<vector<int>> adj(n + 1);
    for (int i = 0; i < m; i++) {
        int u, v;
        cin >> u >> v;
        adj[u].push_back(v);
        adj[v].push_back(u);
    }

    vector<int> parent(n + 1, 0);
    vector<bool> visited(n + 1, false);
    queue<int> q;
    q.push(1);
    visited[1] = true;
    while (!q.empty()) {
        int u = q.front();
        q.pop();
        for (int v : adj[u]) {
            if (!visited[v]) {
                visited[v] = true;
                parent[v] = u;
                q.push(v);
            }
        }
    }

    vector<int> path;
    for (int v = n; v != 0; v = parent[v]) {
        path.push_back(v);
        if (v == 1) break;
    }
    reverse(path.begin(), path.end());

    cout << path.size() << '\n';
    for (size_t i = 0; i < path.size(); i++) {
        cout << path[i] << " \n"[i + 1 == path.size()];
    }
    return 0;
}

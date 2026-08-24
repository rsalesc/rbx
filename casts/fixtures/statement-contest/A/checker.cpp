#include "testlib.h"

// The docs snippet leans on testlib pulling `std` into scope; with GCC 15 it
// does not, so the fixture spells the dependency out.
#include <set>
#include <vector>
using namespace std;

// The path checker from docs/setters/grading/checkers.md: the participant
// prints K followed by K vertices forming a simple path from 1 to N.
int main(int argc, char *argv[]) {
    registerTestlibCmd(argc, argv);

    int N = inf.readInt();
    int M = inf.readInt();

    vector<set<int>> adj(N + 1);
    for (int i = 0; i < M; i++) {
        int u = inf.readInt();
        int v = inf.readInt();
        adj[u].insert(v);
        adj[v].insert(u);
    }

    int K = ouf.readInt(1, N, "path size");
    vector<int> path(K);
    for (int i = 0; i < K; i++) {
        path[i] = ouf.readInt(1, N, "path vertex");
    }

    ouf.quitif(path[0] != 1, _wa, "path does not start at 1");
    ouf.quitif(path[K - 1] != N, _wa, "path does not end at N");

    set<int> seen;
    for (int i = 0; i < K; i++) {
        ouf.quitif(seen.count(path[i]), _wa, "path is not simple");
        seen.insert(path[i]);
    }

    for (int i = 0; i + 1 < K; i++) {
        ouf.quitif(!adj[path[i]].count(path[i + 1]), _wa,
                   "edge %d-%d does not exist", path[i], path[i + 1]);
    }

    ouf.quitf(_ok, "path with %d vertices found", K);
}

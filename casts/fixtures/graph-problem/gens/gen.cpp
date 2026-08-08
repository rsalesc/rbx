#include "testlib.h"

// Generates a connected graph on N vertices: a random spanning path first, so
// the validator's connectivity check always passes, then extra random edges.
// Usage: gen <n> <m>
int main(int argc, char* argv[]) {
    registerGen(argc, argv, 1);
    int n = atoi(argv[1]);
    int m = atoi(argv[2]);

    std::vector<int> perm(n);
    for (int i = 0; i < n; i++) perm[i] = i + 1;
    shuffle(perm.begin() + 1, perm.end());

    std::set<std::pair<int, int>> edges;
    for (int i = 0; i + 1 < n; i++) {
        int u = perm[i], v = perm[i + 1];
        edges.insert(std::make_pair(std::min(u, v), std::max(u, v)));
    }
    while ((int)edges.size() < m) {
        int u = rnd.next(1, n), v = rnd.next(1, n);
        if (u == v) continue;
        edges.insert(std::make_pair(std::min(u, v), std::max(u, v)));
    }

    printf("%d %d\n", n, (int)edges.size());
    for (std::set<std::pair<int, int>>::iterator it = edges.begin();
         it != edges.end(); ++it) {
        // Edges are deduped as (min, max) but printed in a random orientation,
        // so `u` and `v` each reach both ends of their declared range and -v1
        // reports no unhit bound.
        if (rnd.next(2) == 0) {
            printf("%d %d\n", it->first, it->second);
        } else {
            printf("%d %d\n", it->second, it->first);
        }
    }
    return 0;
}

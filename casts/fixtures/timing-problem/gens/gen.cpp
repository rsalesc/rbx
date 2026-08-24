#include <cstdio>
#include <cstdlib>

// Minimal generator: n values in [1, k], drawn from a seeded LCG so the same
// arguments always produce the same test.
// Usage: gen <n> <k> <seed>
int main(int argc, char* argv[]) {
    if (argc != 4) {
        return 1;
    }
    int n = atoi(argv[1]);
    int k = atoi(argv[2]);
    unsigned long long state = (unsigned long long)atoi(argv[3]) + 88172645463325252ULL;

    printf("%d %d\n", n, k);
    for (int i = 0; i < n; i++) {
        state = state * 6364136223846793005ULL + 1442695040888963407ULL;
        printf("%d%c", (int)((state >> 33) % k) + 1, i + 1 == n ? '\n' : ' ');
    }
    return 0;
}

#include "testlib.h"

// The checker from docs/setters/custom-checker-walkthrough.md: any pair (a, b)
// with a + b = N is correct, so the model answer is never consulted.
int main(int argc, char* argv[]) {
    registerTestlibCmd(argc, argv);

    // Read the input: the target sum N.
    int n = inf.readInt();

    // Read the participant's two integers, enforcing 1 <= a, b <= n - 1.
    int a = ouf.readInt(1, n - 1, "a");
    int b = ouf.readInt(1, n - 1, "b");

    // The pair must sum to exactly N.
    if (a + b != n) {
        quitf(_wa, "a + b = %d, expected %d", a + b, n);
    }

    quitf(_ok, "%d + %d = %d", a, b, n);
}

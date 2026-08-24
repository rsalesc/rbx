#include "testlib.h"

using namespace std;

// Usage: gen <N.max> <A.max> [seed]
// testlib seeds its RNG from argv, so the same call always reproduces the same
// testcase -- which is what makes a stress-test finding permanent once saved.
int main(int argc, char *argv[]) {
    registerGen(argc, argv, 1);

    int n = rnd.next(1, opt<int>(1));
    cout << n << endl;
    for (int i = 0; i < n; i++) {
        if (i) cout << " ";
        cout << rnd.next(1, opt<int>(2));
    }
    cout << endl;
}

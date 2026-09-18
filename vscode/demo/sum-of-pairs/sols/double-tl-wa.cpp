#include <ctime>
#include <iostream>
using namespace std;

// The other, independent double-TL fact -- and the nastier one.
//
// Declared `tle`, and it times out, so its expectation is met and the run
// passes. But it fits inside double TL, which means rbx got to see what it
// would have answered had the clock not stopped it: the wrong number. rbx
// prints
//
//   WARNING The solution still finished in double TL, but failed with WA on big.
//
// Slow is not why this solution fails. It is *wrong*, and it is only labelled
// `tle` because the time limit reaches it first -- so the package is
// documenting a slowness bug that does not exist and hiding a correctness one
// that does. A view that reads only the verdict draws this identically to
// double-tl.cpp next to it.
//
// Same timing shape as double-tl.cpp: slow only on `big`'s second testcase, so
// nothing upstream is skipped.

static void burn_cpu_ms(double ms) {
    const clock_t start = clock();
    volatile unsigned long long s = 0;
    while ((double)(clock() - start) * 1000.0 / CLOCKS_PER_SEC < ms) {
        for (int i = 0; i < 100000; ++i) {
            s += i;
        }
    }
}

int main() {
    long long a, b;
    cin >> a >> b;
    long long ans = a + b;
    if (b >= 1000000000LL) {
        burn_cpu_ms(1300);
        // ...and gets it wrong, on exactly the testcase it is too slow for.
        ans += 1;
    }
    cout << ans << endl;
    return 0;
}

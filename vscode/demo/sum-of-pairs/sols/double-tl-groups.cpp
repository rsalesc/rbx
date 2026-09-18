#include <ctime>
#include <iostream>
using namespace std;

// Both double-TL facts at once, raised by two *different* groups.
//
// `edge` is slow but right; `big` is slow and wrong. Neither is a mismatch --
// both declare `tle` and both get one -- so the run passes and rbx prints two
// separate warnings:
//
//   WARNING The solution still passed in double TL on edge.
//   WARNING The solution still finished in double TL, but failed with WA on big.
//
// This is the fixture for the bug the console side hit in #607. The two facts
// are unions over the pooled expectation and every group, so one solution can
// raise both, and reporting them together would have to blame a single group
// list for both -- which is how one of them was lost entirely. Each warning
// names only the group that raised it, and this solution is the case that
// tells a correct implementation from a merged one.
//
// `main` stays fast and correct on purpose: `big` depends on it, and a skipped
// testcase means rbx has no evidence the solution fits in double TL at all.

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
    // Slow on `edge`'s max-int case and on both of `big`'s.
    if (a > 1000000000LL) {
        burn_cpu_ms(1300);
    }
    long long ans = a + b;
    // Wrong on `big`'s second case only, so `edge` stays slow-but-right and the
    // two groups raise different facts.
    if (b >= 1000000000LL) {
        ans += 1;
    }
    cout << ans << endl;
    return 0;
}

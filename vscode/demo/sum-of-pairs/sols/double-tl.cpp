#include <ctime>
#include <iostream>
using namespace std;

// Declared `tle`, and it does time out -- but only just.
//
// `rbx run` defaults to -v4, which judges at TWICE the time limit and rewrites
// an over-limit run to TLE while remembering the verdict underneath. This
// solution burns 1300ms: past the 1000ms limit, comfortably inside the 2000ms
// the sandbox actually allows. So it is reported TLE, its `tle` expectation is
// met, and the run passes -- while rbx prints
//
//   WARNING The solution still passed in double TL on big.
//
// That is a real problem hiding inside a green run: a solution this close to
// the limit is borderline, not decisively slow, and the testset does not
// actually prove it should fail. Nothing about the verdict says so.
//
// Slow only on `big`'s second testcase. Timing out earlier would fail `main`,
// which `big` depends on, and a skipped testcase suppresses the warning --
// rbx will not claim a solution fits in double TL over tests that never ran.

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
    if (b >= 1000000000LL) {
        burn_cpu_ms(1300);
    }
    // Always correct: 64-bit, like main.cpp. The only thing wrong here is when.
    cout << a + b << endl;
    return 0;
}

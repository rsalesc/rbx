#include "testlib.h"

// Full marks for the exact sum, 10 percentage points less per unit off.
int main(int argc, char *argv[]) {
    registerTestlibCmd(argc, argv);
    long long expected = ans.readLong();
    long long got = ouf.readLong();
    if (got == expected)
        quitf(_ok, "exact");
    long long off = got > expected ? got - expected : expected - got;
    int percent = off >= 10 ? 0 : 100 - 10 * (int)off;
    quitp(percent, "off by %lld", off);
}

#include "testlib.h"

// Token-comparison checker, equivalent to testlib's wcmp. Lives in the package
// (rather than relying on the default checker) so the e2e runner provisions
// testlib.h next to it and the fixture compiles offline, without a preset.
int main(int argc, char* argv[]) {
    registerTestlibCmd(argc, argv);

    int n = 0;
    while (!ans.seekEof() && !ouf.seekEof()) {
        n++;
        std::string j = ans.readWord();
        std::string p = ouf.readWord();
        if (j != p) {
            quitf(_wa, "%d%s words differ - expected: '%s', found: '%s'", n,
                  englishEnding(n).c_str(), compress(j).c_str(),
                  compress(p).c_str());
        }
    }

    if (ans.seekEof() && ouf.seekEof()) {
        quitf(_ok, "%d token(s)", n);
    }
    quitf(_wa, "unexpected number of tokens");
}

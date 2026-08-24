#include "testlib.h"

using namespace std;

// A deliberately chatty checker: it dumps context to stderr before its verdict
// line, so the scenario can tell the full stderr apart from the single line
// that reaches the verdict.
int main(int argc, char* argv[]) {
    registerTestlibCmd(argc, argv);

    int expected = ans.readInt();
    int got = ouf.readInt();

    fprintf(stderr, "CHK_CONTEXT_MARKER expected=%d\n", expected);
    fprintf(stderr, "CHK_CONTEXT_MARKER got=%d\n", got);

    if (expected != got) {
        quitf(_wa, "CHK_VERDICT_MARKER differ");
    }
    quitf(_ok, "CHK_VERDICT_MARKER equal");
}

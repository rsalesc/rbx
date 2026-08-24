#include "testlib.h"

using namespace std;

// A checker that dumps diagnostics to stderr before its verdict line, so tests
// can tell the full stderr apart from the last line rbx keeps in
// `CheckerResult.message`.
int main(int argc, char *argv[]) {
  registerTestlibCmd(argc, argv);

  fprintf(stderr, "diagnostic line 1\n");
  fprintf(stderr, "diagnostic line 2\n");

  quitf(_wa, "verdict line");
}

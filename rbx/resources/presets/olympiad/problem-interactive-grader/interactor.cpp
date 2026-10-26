#include "testlib.h"
#include "rbx.h"
// A testlib interactor for a problem with a grader stub. Docs:
// https://rsalesc.github.io/rbx/setters/grading/interactors/
//
// Include testlib.h BEFORE rbx.h: the grader helpers need testlib.
//
// Interactors have a non-conventional stream setup:
// - inf:  reads the test input (the solution can NOT see this file);
// - ouf:  reads what the grader stub wrote to its stdout;
// - cout: writes to the grader stub's stdin.

using namespace std;

int main(int argc, char *argv[]) {
  // Like registerInteraction, but reads the test past its hidden header.
  rbx::registerGraderInteraction(argc, argv);

  // The test input holds the search range and the secret number.
  int N = inf.readInt();
  int S = inf.readInt();

  int MAX_Q = getVar<int>("Q.max"); // Read from package vars.

  // Tell the stub the size of the search range. Always `endl` (never '\n'):
  // the stub is blocked waiting for this line, so it must be flushed.
  cout << N << endl;

  int queries = 0;
  while (true) {
    // The stub sends `? x` for each call to guess(x), and `! s` once
    // find_secret returns s.
    string op = ouf.readToken("[?!]", "op");
    int X = ouf.readInt(1, N, "x");
    if (op == "!") {
      if (X != S) {
        quitf(_wa, "answered %d, but the secret number is %d", X, S);
      }
      quitf(_ok, "found the secret number in %d guesses", queries);
    }
    if (++queries > MAX_Q) {
      quitf(_wa, "exceeded the maximum number of guesses");
    }
    cout << (X == S ? 0 : (S > X ? 1 : -1)) << endl;
  }
}

#include "rbx.h"
#include "testlib.h"
// A testlib interactor. Docs:
// https://rsalesc.github.io/rbx/setters/grading/interactors/
//
// Interactors have a non-conventional stream setup:
// - inf:  reads the test input (the solution can NOT see this file);
// - ouf:  reads what the solution wrote to its stdout;
// - cout: writes to the solution's stdin;
// - tout: writes the output file (a log, useful for debugging/judges).

using namespace std;

int main(int argc, char *argv[]) {
  registerInteraction(argc, argv);

  // The test input holds the search range and the secret number.
  int N = inf.readInt();
  int S = inf.readInt();

  int MAX_Q = getVar<int>("Q.max"); // Read from package vars.

  // Tell the solution the size of the search range. Always `endl` (never
  // '\n'): the solution is blocked waiting for this line, so it must be
  // flushed right away.
  cout << N << endl;

  for (int i = 0; i < MAX_Q; i++) {
    int X = ouf.readInt(1, N); // Read a guess, checking it is in range.

    if (X < S) {
      cout << "<" << endl;
    } else if (X > S) {
      cout << ">" << endl;
    } else {
      cout << "=" << endl;
      tout << i + 1 << endl; // Log the number of guesses to the output file.
      quitf(_ok, "found the secret number in %d guesses", i + 1);
    }
  }

  quitf(_wa, "exceeded the maximum number of guesses");
}

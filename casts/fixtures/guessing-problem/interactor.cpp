#include "testlib.h"
#include "rbx.h"

using namespace std;

// The guessing-game interactor from docs/setters/grading/interactors.md.
// - inf: the input file (N and the secret S)
// - ouf: the participant's output
// - cout: the participant's input
// - tout: the output file
int main(int argc, char *argv[]) {
    registerInteraction(argc, argv);

    int N = inf.readInt();
    int S = inf.readInt();

    int MAX_Q = getVar<int>("Q.max");

    // The problem statement says the interactor hands N to the solution first.
    // The snippet in the docs page omits this line, which deadlocks any
    // solution that opens by reading N.
    cout << N << endl;

    for (int i = 0; i < MAX_Q; i++) {
        // Guesses arrive as `? X`. The docs snippet reads only the integer,
        // which rejects the very format the statement above specifies.
        ouf.readToken("\\?");
        int X = ouf.readInt(1, N);

        if (X < S) {
            cout << "<" << endl;
        } else if (X > S) {
            cout << ">" << endl;
        } else {
            cout << "=" << endl;
            tout << i + 1 << endl;
            quitf(_ok, "found the secret number in %d guesses", i + 1);
        }
    }

    quitf(_wa, "exceeded the maximum number of guesses");
}

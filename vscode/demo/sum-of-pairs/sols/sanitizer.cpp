#include <iostream>
using namespace std;

// Declared `ac`, and it IS correct -- on every testcase, in every group.
//
// The answer is built entirely in 64-bit, exactly like main.cpp, so nothing a
// checker can see is ever wrong. What is wrong is the leftover 32-bit
// accumulator below: on any test whose sum leaves int range it overflows, which
// is undefined behaviour. Under `rbx run -s` the solution is built with
// `-fsanitize=address,undefined`, UBSAN reports the overflow on stderr and --
// because it recovers rather than aborting -- the program carries on and prints
// the right answer anyway. So the run is green and rbx still prints
//
//   WARNING The solution had sanitizer errors or warnings, marked with *.
//   See their stderr for more details.
//
// That is the same shape of problem as double-tl.cpp: a real defect hiding
// inside a run where `status` is OK, `matchesExpectation` is true and the chip
// says AC. Every channel that answers "did the declaration hold" says yes.
//
// It fires on a SUBSET, which is the half worth watching in the view:
//
//   samples, main   sums stay well inside int         -- clean
//   edge            only `2147483647 1` overflows     -- one testcase of three
//   big             both testcases overflow           -- the whole group
//
// so the solution's warning names `edge, big` and not the two groups that ran
// clean, and inside `edge` only the row that actually tripped carries the mark.
//
// Note this is invisible without `-s`: an ordinary `rbx run` compiles no
// sanitizer in, the overflow goes unremarked, and the solution is simply AC.

int main() {
    long long a, b;
    cin >> a >> b;

    // The bug. `volatile` so no optimizer is tempted to drop a computation
    // whose result nobody reads -- the point is that it runs, not that it is
    // used. Both operands fit in an int on every test the package generates;
    // it is the addition that leaves the range.
    volatile int narrowed = (int)a;
    narrowed = narrowed + (int)b;

    // The real answer, in the width the problem actually needs.
    cout << a + b << endl;
    return 0;
}

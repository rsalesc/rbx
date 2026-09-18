#include <iostream>
using namespace std;

// Correct, and compiles with warnings. Nothing about the *run* is wrong: it
// answers every group, matches its `ac` declaration, and draws a clean green
// row in the tree. The compiler is the only thing with anything to say about
// it, which before the Compilation Findings panel meant nothing on disk said
// it at all.
//
// Two warnings with two different flags, so the panel's expanded row has more
// than one kind of line to list. Both flags are ones rbx actually turns on:
// it compiles with `-Wall -Wshadow -Wno-unused-result -Wno-sign-compare
// -Wno-char-subscripts`, so the usual signed/unsigned comparison would be
// silent here.
long long total = 0;

int main() {
    long long a, b;
    cin >> a >> b;

    // -Wshadow: hides the file-scope `total` above.
    long long total = a + b;

    // -Wunused-variable: declared, never read.
    int leftover;

    cout << total << endl;
    return 0;
}

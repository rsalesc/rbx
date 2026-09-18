#include <iostream>
using namespace std;

// MISMATCH (pooled): declared `ac`, but overflows on the `big` group.
//
// The realistic version of an expectation miss: the setter believes this is a
// correct solution and declared it as one. It is not, and the run says so --
// expected ACCEPTED, got WRONG_ANSWER. This is the case the run view has to
// make impossible to scroll past.
int main() {
    int a, b;
    cin >> a >> b;
    cout << a + b << endl;
    return 0;
}

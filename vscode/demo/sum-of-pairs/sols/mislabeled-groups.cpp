#include <iostream>
using namespace std;

// MISMATCH (per-group only): the pooled expectation is MET, and only the
// per-group layer catches this one.
//
// Declared `incorrect` overall -- which holds, it does fail on `big` -- but
// every group is declared `tle`, and it is not slow anywhere. So a renderer
// that reports this as "expected INCORRECT, got WA" names an expectation that
// was in fact satisfied. The row has to blame the groups, not the pooled
// declaration.
//
// Same shape as sols/mislabeled.cpp in tests/e2e/testdata/outcome-per-group.
int main() {
    long long a, b;
    cin >> a >> b;
    cout << (int)((int)a + (int)b) << endl;
    return 0;
}

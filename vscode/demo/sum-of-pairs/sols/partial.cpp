#include <iostream>
using namespace std;

// Partially correct: sums with 32-bit arithmetic, so it is right on the small
// groups and overflows on `big`. The point of this one is that a single
// solution shows different verdicts per group in the tree.
int main() {
    long long a, b;
    cin >> a >> b;
    cout << (int)((int)a + (int)b) << endl;
    return 0;
}

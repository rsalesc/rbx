#include <iostream>
using namespace std;

// Correct, but deliberately lazy: burns a few hundred ms before answering.
// Declared `ac or tle` so it is allowed to fall either way -- which also keeps
// it out of the time-limit inference, and gives the tree a row with a visibly
// larger time than the rest.
int main() {
    long long a, b;
    cin >> a >> b;
    volatile unsigned long long s = 0;
    for (unsigned long long i = 0; i < 300000000ULL; ++i) {
        s += i;
    }
    cout << (a + b + (long long)(s & 0)) << endl;
    return 0;
}

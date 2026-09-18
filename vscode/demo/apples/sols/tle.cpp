#include <iostream>
using namespace std;

// Slow solution: busy loop ensures we exceed the configured timeLimit
// (1000ms; rbx run uses 2x for verification = 2000ms cap on wall time).
int main() {
    int a, b;
    cin >> a >> b;
    volatile unsigned long long s = 0;
    for (unsigned long long i = 0; i < 10000000000ULL; ++i) {
        s += i;
    }
    cout << (a + b + (int)(s & 0)) << endl;
    return 0;
}

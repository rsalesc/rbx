#include <iostream>
using namespace std;

// Accepted solution that deliberately takes a couple hundred milliseconds, so
// the lower bound it imposes is far above what `sols/not_slow.cpp` allows.
int main() {
    int a, b;
    cin >> a >> b;
    volatile unsigned long long s = 0;
    for (unsigned long long i = 0; i < 500000000ULL; ++i) {
        s += i;
    }
    cout << (a + b + (int)(s & 0)) << endl;
    return 0;
}

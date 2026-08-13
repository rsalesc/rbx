#include <iostream>
using namespace std;

// Solution expected to be too slow: it does ~50x the work of the accepted one,
// so it terminates well within the inference timeout while leaving plenty of
// room between the lower and the upper bound.
int main() {
    int a, b;
    cin >> a >> b;
    volatile unsigned long long s = 0;
    for (unsigned long long i = 0; i < 1000000000ULL; ++i) {
        s += i;
    }
    cout << (a + b + (int)(s & 0)) << endl;
    return 0;
}

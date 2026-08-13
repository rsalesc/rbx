#include <iostream>
using namespace std;

// Accepted solution with a deliberate, small amount of work so its measured
// time is comfortably above zero and the lower bound is meaningful.
int main() {
    int a, b;
    cin >> a >> b;
    volatile unsigned long long s = 0;
    for (unsigned long long i = 0; i < 20000000ULL; ++i) {
        s += i;
    }
    cout << (a + b + (int)(s & 0)) << endl;
    return 0;
}

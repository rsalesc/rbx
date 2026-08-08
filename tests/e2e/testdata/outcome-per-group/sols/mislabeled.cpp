#include <iostream>
using namespace std;

// Same program as `partial.cpp`, but the package declares the wrong per-group
// expectation for it: it is claimed to time out everywhere, while it is really
// accepted on `small` and wrong on `big`.
int main() {
    int a, b;
    cin >> a >> b;
    int sum = a + b;
    cout << (sum <= 100 ? sum : 0) << endl;
    return 0;
}

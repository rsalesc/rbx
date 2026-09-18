#include <iostream>
using namespace std;

int main() {
    // 64-bit: the `big` group feeds two values that each fit in an int but
    // whose sum does not.
    long long a, b;
    cin >> a >> b;
    cout << a + b << endl;
    return 0;
}

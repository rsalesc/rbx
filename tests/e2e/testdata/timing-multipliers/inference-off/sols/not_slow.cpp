#include <iostream>
using namespace std;

// Declared as too slow, but returns immediately: the upper bound it sets is
// below the lower bound the accepted solution imposes.
int main() {
    int a, b;
    cin >> a >> b;
    cout << a + b << endl;
    return 0;
}

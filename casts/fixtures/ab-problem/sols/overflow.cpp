#include <iostream>
using namespace std;

// Deliberately wrong: overflows on the large testcase, so `rbx run` has an
// interesting verdict to show next to the accepted solution.
int main() {
    int a, b;
    cin >> a >> b;
    cout << (int)(a + b) << endl;
    return 0;
}

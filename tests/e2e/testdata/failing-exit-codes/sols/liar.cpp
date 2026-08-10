#include <iostream>
using namespace std;

// Declared `ac` in problem.rbx.yml, but prints the product instead of the sum.
// That mismatch is what `rbx run` has to fail on.
int main() {
    int a, b;
    cin >> a >> b;
    cout << a * b << endl;
    return 0;
}

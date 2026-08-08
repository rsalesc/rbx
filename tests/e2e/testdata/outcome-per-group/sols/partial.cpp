#include <iostream>
using namespace std;

// Partial solution: only correct while the sum is small, so it is accepted on
// the `small` testgroup and wrong on `big`.
int main() {
    int a, b;
    cin >> a >> b;
    int sum = a + b;
    cout << (sum <= 100 ? sum : 0) << endl;
    return 0;
}

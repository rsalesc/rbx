#include <iostream>
using namespace std;

// Wrong only on the first `small` test (`5 6`).
int main() {
    int a, b;
    cin >> a >> b;
    cout << (a == 5 ? 0 : a + b) << endl;
    return 0;
}

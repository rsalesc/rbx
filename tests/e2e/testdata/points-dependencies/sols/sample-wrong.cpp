#include <iostream>
using namespace std;

// Wrong only on the first sample (`1 2`).
int main() {
    int a, b;
    cin >> a >> b;
    cout << (a == 1 ? 0 : a + b) << endl;
    return 0;
}

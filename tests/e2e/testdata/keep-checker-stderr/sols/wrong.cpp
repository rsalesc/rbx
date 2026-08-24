#include <iostream>
using namespace std;

// Off by one, so the chatty checker always reaches its WA branch.
int main() {
    int a, b;
    cin >> a >> b;
    cout << a + b + 1 << endl;
    return 0;
}

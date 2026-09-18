#include <iostream>
#include <vector>
using namespace std;

// Runtime error: reads the input fine, then indexes past the end of a vector
// through at(), which throws and aborts with a non-zero exit code (RTE).
int main() {
    int a, b;
    cin >> a >> b;
    vector<int> v(1, a + b);
    cout << v.at(b + 10) << endl;
    return 0;
}

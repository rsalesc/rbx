#include <iostream>
using namespace std;

int main() {
    int a, b;
    cin >> a >> b;
    // Distinctive debug line written to stderr; irun -p should surface it
    // under its own "Stderr" section on stdout.
    cerr << "DBG_STDERR_MARKER a=" << a << endl;
    cout << a + b << endl;
    return 0;
}

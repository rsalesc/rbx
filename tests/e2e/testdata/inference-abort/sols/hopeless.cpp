#include <ctime>
#include <iostream>
using namespace std;

// Correct, but burns far more CPU than the inference timeout allows, so it is
// killed at the cap on every testcase it is given. It bounds nothing from
// above, which is exactly why running it more than once is wasted time.
int main() {
    int a, b;
    cin >> a >> b;
    clock_t start = clock();
    while (((double)(clock() - start)) / CLOCKS_PER_SEC < 5.0) {
    }
    cout << (a + b) << endl;
    return 0;
}

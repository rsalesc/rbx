#include <iostream>
#include <vector>
using namespace std;

// Memory limit exceeded: allocates and *touches* ~1GiB against the problem's
// 256MB limit. Touching matters -- an untouched allocation may never be backed
// by real pages, and the sandbox would let it through.
int main() {
    int a, b;
    cin >> a >> b;
    const size_t kInts = 256ULL * 1024 * 1024;  // 1GiB of int.
    vector<int> hog(kInts);
    for (size_t i = 0; i < kInts; i += 1024) {
        hog[i] = (int)i;
    }
    cout << (a + b + hog[0]) << endl;
    return 0;
}

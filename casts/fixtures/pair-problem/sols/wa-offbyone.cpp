#include <bits/stdc++.h>
using namespace std;

int32_t main() {
    int64_t n;
    cin >> n;
    cout << 2 << " " << n - 1 << endl;  // bug: 2 + (n - 1) = n + 1
}

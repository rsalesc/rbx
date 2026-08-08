#include <bits/stdc++.h>

using namespace std;

int32_t main() {
    int n;
    cin >> n;

    int64_t ans = 0;
    for (int i = 0; i < n; i++) {
        int x;
        cin >> x;
        ans += x;
    }

    cout << ans << endl;
}

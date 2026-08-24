#include <algorithm>
#include <cstdio>
#include <vector>
using namespace std;

// Declared too slow, but it is not: it sorts a few extra times and is still
// far inside the bound the time limit demands of a rejected solution. Swapped
// in by the `time-upper-bound-violation` recording so the check has something
// to catch. Not part of the package.
int main() {
    int n, k;
    scanf("%d %d", &n, &k);
    vector<int> a(n);
    for (int i = 0; i < n; i++) {
        scanf("%d", &a[i]);
    }
    for (int round = 0; round < 4; round++) {
        sort(a.begin(), a.end());
        reverse(a.begin(), a.end());
    }
    sort(a.begin(), a.end());

    long long pairs = 0;
    int lo = 0, hi = n - 1;
    while (lo < hi) {
        int sum = a[lo] + a[hi];
        if (sum == k) {
            if (a[lo] == a[hi]) {
                long long run = hi - lo + 1;
                pairs += run * (run - 1) / 2;
                break;
            }
            long long left = 1, right = 1;
            while (lo + left < hi && a[lo + left] == a[lo]) left++;
            while (hi - right > lo && a[hi - right] == a[hi]) right++;
            pairs += left * right;
            lo += left;
            hi -= right;
        } else if (sum < k) {
            lo++;
        } else {
            hi--;
        }
    }
    printf("%lld\n", pairs);
    return 0;
}

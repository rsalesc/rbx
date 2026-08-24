#include <algorithm>
#include <iostream>
#include <vector>
using namespace std;

// Sort, then count pairs summing to K with two pointers: O(n log n).
int main() {
    int n, k;
    scanf("%d %d", &n, &k);
    vector<int> a(n);
    for (int i = 0; i < n; i++) {
        scanf("%d", &a[i]);
    }
    sort(a.begin(), a.end());

    long long pairs = 0;
    int lo = 0, hi = n - 1;
    while (lo < hi) {
        int sum = a[lo] + a[hi];
        if (sum == k) {
            // Every equal-valued element on the left pairs with every one on
            // the right, so count the two runs and skip past both.
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

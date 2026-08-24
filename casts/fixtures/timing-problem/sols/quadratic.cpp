#include <cstdio>
#include <vector>
using namespace std;

// The naive pass over every pair: O(n^2), and hopeless at these sizes. This is
// the solution the time limit exists to reject.
int main() {
    int n, k;
    scanf("%d %d", &n, &k);
    vector<int> a(n);
    for (int i = 0; i < n; i++) {
        scanf("%d", &a[i]);
    }

    long long pairs = 0;
    for (int i = 0; i < n; i++) {
        for (int j = i + 1; j < n; j++) {
            if (a[i] + a[j] == k) {
                pairs++;
            }
        }
    }
    printf("%lld\n", pairs);
    return 0;
}

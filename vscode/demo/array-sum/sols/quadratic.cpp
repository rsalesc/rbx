#include <cstdio>
#include <vector>

// Recomputes every prefix sum from scratch: O(n^2), instant for `small` and
// `medium`, far over the limit on `large`.
int main() {
  int n;
  scanf("%d", &n);
  std::vector<long long> a(n);
  for (auto &v : a) {
    scanf("%lld", &v);
  }
  volatile long long sum = 0;
  for (int i = 0; i < n; i++) {
    long long prefix = 0;
    for (int j = 0; j <= i; j++) {
      prefix += a[j];
    }
    if (i == n - 1) {
      sum = prefix;
    }
  }
  printf("%lld\n", (long long)sum);
}

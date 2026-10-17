#include <cstdio>

// Forgets the last element whenever n is a multiple of 7: a few scattered
// misses in every group rather than a whole group at once.
int main() {
  int n;
  scanf("%d", &n);
  long long sum = 0;
  for (int i = 0; i < n; i++) {
    long long v;
    scanf("%lld", &v);
    if (n % 7 == 0 && i == n - 1 && v != 0) {
      continue;
    }
    sum += v;
  }
  printf("%lld\n", sum);
}

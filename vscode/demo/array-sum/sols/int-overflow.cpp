#include <cstdio>

// Sums into an `int`: right until the total passes 2^31, which only the tests
// with large values do -- so it fails in clusters, not everywhere.
int main() {
  int n;
  scanf("%d", &n);
  int sum = 0;
  for (int i = 0; i < n; i++) {
    int v;
    scanf("%d", &v);
    sum += v;
  }
  printf("%d\n", sum);
}

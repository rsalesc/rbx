#include <cstdio>
#include <cstdlib>

// Sized for "surely nobody sends more than 100000": crashes on the few tests
// that do, and only those.
static long long a[100000];

int main() {
  int n;
  scanf("%d", &n);
  if (n > 100000) {
    abort();
  }
  long long sum = 0;
  for (int i = 0; i < n; i++) {
    scanf("%lld", &a[i]);
    sum += a[i];
  }
  printf("%lld\n", sum);
}

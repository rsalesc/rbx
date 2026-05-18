#include <bits/stdc++.h>

using namespace std;

// Naively assumes the root is always vertex 1. Wrong: the generator never
// picks vertex 1 as the hidden root.
int main() {
  int n;
  if (scanf("%d", &n) != 1)
    return 0;
  for (int i = 0; i < n - 1; i++) {
    int u, v;
    scanf("%d %d", &u, &v);
  }
  int budget;
  scanf("%d", &budget);

  printf("? 1\n");
  fflush(stdout);
  int sz, dep;
  scanf("%d", &sz);
  scanf("%d", &dep);

  printf("! 1\n");
  fflush(stdout);
  return 0;
}

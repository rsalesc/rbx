#include <bits/stdc++.h>

using namespace std;

// Read the public preamble (tree structure + budget), then probe vertices.
// The unique vertex whose subtree size equals n is the hidden root.
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

  for (int v = 1; v <= n; v++) {
    printf("? %d\n", v);
    fflush(stdout);
    int sz, dep;
    scanf("%d", &sz);
    scanf("%d", &dep);
    if (sz == n) {
      printf("! %d\n", v);
      fflush(stdout);
      return 0;
    }
  }

  // Fallback (should be unreachable on valid input).
  printf("! 1\n");
  fflush(stdout);
  return 0;
}

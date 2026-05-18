#include <bits/stdc++.h>

using namespace std;

// Probes the same vertex far more than the allowed limit before answering,
// so the checker rejects it for exceeding the global query budget.
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

  for (int i = 0; i < 1000; i++) {
    printf("? 1\n");
    fflush(stdout);
    int sz, dep;
    scanf("%d", &sz);
    scanf("%d", &dep);
  }

  printf("! 1\n");
  fflush(stdout);
  return 0;
}

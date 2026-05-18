#include "testlib.h"
#include <bits/stdc++.h>

using namespace std;

int main(int argc, char *argv[]) {
  registerGen(argc, argv, 1);

  int n = rnd.next(4, 10);
  printf("%d\n", n);

  // Random labelled tree: attach each new vertex to a random earlier one.
  vector<int> perm(n);
  for (int i = 0; i < n; i++)
    perm[i] = i + 1;
  shuffle(perm.begin(), perm.end());

  for (int i = 1; i < n; i++) {
    int parent = perm[rnd.next(0, i - 1)];
    int child = perm[i];
    if (rnd.next(0, 1))
      printf("%d %d\n", parent, child);
    else
      printf("%d %d\n", child, parent);
  }

  // Hidden root is never vertex 1, so the trivial "answer 1" solution fails.
  int root = rnd.next(2, n);
  printf("%d\n", root);

  return 0;
}

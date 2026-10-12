#include <cstdio>

int main() {
  int r;
  scanf("%d", &r);
  for (int i = 0; i < r; i++) {
    int v;
    scanf("%d", &v);
    printf("%d\n", v ^ 12345);
    fflush(stdout);
  }
}

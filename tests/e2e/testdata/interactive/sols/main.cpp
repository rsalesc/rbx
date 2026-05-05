#include <cstdio>
#include <cstring>

using namespace std;

int main() {
  int n;
  scanf("%d", &n);

  int l = 1, r = n;
  while (l != r) {
    int mid = (l + r + 1) / 2;
    printf("%d\n", mid);
    fflush(stdout);

    char response[3];
    scanf("%s", response);
    if (strcmp(response, "<") == 0)
      r = mid - 1;
    else
      l = mid;
  }

  printf("! %d\n", l);
  fflush(stdout);
}

#include <cstdio>
#include <cstdlib>

#include "guessing.h"
// A grader stub, compiled together with every solution. It turns the
// participant's function calls into messages to the interactor, which runs as
// a separate program. Docs:
// https://rsalesc.github.io/rbx/setters/grading/graders/

int guess(int x) {
  // Always flush: the interactor is blocked waiting for this line.
  std::printf("? %d\n", x);
  std::fflush(stdout);
  int response;
  if (std::scanf("%d", &response) != 1) {
    // The interactor already gave its verdict and hung up.
    std::exit(0);
  }
  return response;
}

int main() {
  int n;
  if (std::scanf("%d", &n) != 1) {
    return 0;
  }
  int answer = find_secret(n);
  std::printf("! %d\n", answer);
  std::fflush(stdout);
  return 0;
}

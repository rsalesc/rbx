#include <cstdio>
#include <vector>

#include "rbx.h"
#include "sumgame.h"

int main() {
  rbx::grader::Grader grader;

  int n;
  if (std::scanf("%d", &n) != 1) {
    return 1;
  }
  std::vector<long long> a(n);
  for (auto &x : a) {
    std::scanf("%lld", &x);
  }

  long long result = grader.run([&] {
    long long r = sum_all(a);
    // BEGIN SECRET
    if (r == -1) {
      grader.wrong_answer("sum_all gave up");
    }
    // END SECRET
    return r;
  });

  std::printf("%lld\n", result);
  return 0;
}

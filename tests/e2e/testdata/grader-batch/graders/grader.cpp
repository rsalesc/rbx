#include <cstdio>
#include <vector>

#include "rbx.h"
#include "sumgame.h"

int main() {
  rbx::grader::start();
  int n;
  if (std::scanf("%d", &n) != 1) {
    return 1;
  }
  std::vector<long long> a(n);
  for (auto &x : a) {
    std::scanf("%lld", &x);
  }
  rbx::grader::close_input();

  rbx::grader::before_call();
  long long result = sum_all(a);
  // BEGIN SECRET
  if (result == -1) {
    rbx::grader::verdict(rbx::grader::Verdict::WA, "sum_all gave up");
  }
  // END SECRET
  rbx::grader::after_call();

  std::printf("%lld\n", result);
  return 0;
}

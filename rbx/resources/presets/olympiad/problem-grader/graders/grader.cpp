#include <cstdio>

#include "rbx.h"
#include "aplusb.h"
// A grader, compiled together with every solution. It owns main(): it reads
// the test, calls the participant's function and prints what it returned.
// Docs: https://rsalesc.github.io/rbx/setters/grading/graders/

int main() {
  // Reads and checks the hidden header rbx puts at the top of every test.
  rbx::grader::Grader grader;

  long long a, b;
  if (std::scanf("%lld %lld", &a, &b) != 2) {
    return 1;
  }

  // `run` closes stdin and frames the output around the participant's call.
  long long result = grader.run([&] {
    long long r = sum(a, b);
    // BEGIN SECRET
    // Judge-only checks go here; participants' copy of the grader drops them.
    // END SECRET
    return r;
  });

  std::printf("%lld\n", result);
  return 0;
}

#include <csignal>
#include <cstdio>
#include <cstdlib>

#include "relay.h"

int main(int argc, char *argv[]) {
  // The interactor may finish while we still write: exit quietly instead.
  std::signal(SIGPIPE, SIG_IGN);
  int index = std::atoi(argv[1]);
  long long v;
  while (std::scanf("%lld", &v) == 1 && v != -1) {
    std::printf("%lld\n", relay(index, v));
    std::fflush(stdout);
  }
  return 0;
}

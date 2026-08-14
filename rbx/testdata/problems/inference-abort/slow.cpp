#include <ctime>
#include <iostream>

// Correct, but burns far more CPU than any inference timeout these tests use,
// so it is always killed at the cap.
void busy_loop() {
  double wait = 3.0;
  clock_t start = clock();
  while (((double)(clock() - start)) / CLOCKS_PER_SEC < wait) {
  }
}

int main() {
  int n;
  std::cin >> n;
  busy_loop();
  std::cout << n * 2 << std::endl;
  return 0;
}

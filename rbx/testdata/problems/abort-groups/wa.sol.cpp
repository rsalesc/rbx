// Wrong exactly on the inputs of the `small` group, correct everywhere else.
#include <iostream>

int main() {
  long long n;
  std::cin >> n;
  if (n < 10) {
    n++;
  }
  std::cout << n << std::endl;
  return 0;
}

#pragma once

namespace math {
long long factorial(int n) {
  if (n <= 1)
    return 1;
  return n * factorial(n - 1);
}
} // namespace math
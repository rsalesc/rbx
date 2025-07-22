#ifndef SHARED_HEADER_H
#define SHARED_HEADER_H

#include <algorithm>
#include <iostream>
#include <vector>

// Common competitive programming utilities
namespace cp {
template <typename T> void print_vector(const std::vector<T> &v) {
  for (const auto &item : v) {
    std::cout << item << " ";
  }
  std::cout << std::endl;
}
} // namespace cp

#endif
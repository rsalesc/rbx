#pragma once

namespace utils {
template <typename T> T gcd(T a, T b) { return b == 0 ? a : gcd(b, a % b); }
} // namespace utils
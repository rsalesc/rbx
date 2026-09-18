#include <cstdio>

// A visualization that is NOT an image, on purpose.
//
// `Visualizer.extension` is a free-form string, so rbx promises nothing about
// what a visualizer writes. The Tests panel must therefore refuse to guess: an
// extension it has no viewer for gets an "open in editor" affordance instead of
// a broken <img>. Problem A covers the image path with two SVG visualizers and
// `vis/baskets.cpp` covers the HTML one; this is the path that must not guess,
// which is the one that breaks silently if anybody ever "helpfully" widens the
// mapping.
//
// Declared on the `samples` group alone, so one testset carries a viewer-less
// cell and an HTML cell at once.
//
// Invoked as `vis <visualization.txt> <input.txt> [answer.txt]`.
int main(int argc, char *argv[]) {
  if (argc < 3) {
    return 1;
  }

  FILE *in = std::fopen(argv[2], "r");
  if (in == nullptr) {
    return 1;
  }
  long long a = 0, b = 0;
  if (std::fscanf(in, "%lld %lld", &a, &b) != 2) {
    std::fclose(in);
    return 1;
  }
  std::fclose(in);

  FILE *out = std::fopen(argv[1], "w");
  if (out == nullptr) {
    return 1;
  }

  std::fprintf(out, "a = %lld\n", a);
  for (long long i = 0; i < a && i < 100; i++) {
    std::fputc('#', out);
  }
  std::fprintf(out, "\n\nb = %lld\n", b);
  for (long long i = 0; i < b && i < 100; i++) {
    std::fputc('#', out);
  }
  std::fprintf(out, "\n\nsum = %lld\n", a + b);
  std::fclose(out);
  return 0;
}

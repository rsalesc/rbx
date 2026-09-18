#include <cmath>
#include <cstdio>

// Input visualizer: draws the two operands as bars.
//
// Invoked by rbx as `vis <visualization.svg> <input.txt> [answer.txt]`, so
// argv[1] is the file to WRITE and argv[2] is the testcase input. The answer is
// passed too and deliberately ignored here -- that is what `vis/answer.cpp` is
// for, and having one of each is what puts both an `input` and an `output` cell
// in the gallery for every testcase.
//
// Bars are log-scaled. The interesting testcases in this package span 0 to
// 2^31-1, and on a linear scale every group but `big` would draw as a bar of
// zero width.
static double scale(long long v) {
  if (v <= 0) {
    return 0.0;
  }
  return std::log10((double)v + 1.0) / std::log10(2147483648.0);
}

static void bar(FILE *out, const char *name, long long value, int y,
                const char *fill) {
  double width = scale(value) * 520.0;
  std::fprintf(out,
               "  <text x=\"16\" y=\"%d\" font-family=\"monospace\" "
               "font-size=\"13\" fill=\"#888\">%s</text>\n",
               y + 14, name);
  std::fprintf(out,
               "  <rect x=\"44\" y=\"%d\" width=\"%.2f\" height=\"20\" "
               "rx=\"3\" fill=\"%s\"/>\n",
               y, width < 2.0 ? 2.0 : width, fill);
  std::fprintf(out,
               "  <text x=\"%.2f\" y=\"%d\" font-family=\"monospace\" "
               "font-size=\"13\" fill=\"#ccc\">%lld</text>\n",
               52.0 + (width < 2.0 ? 2.0 : width), y + 14, value);
}

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

  // No background rect: the gallery renders these over the editor's own
  // surface, and a hardcoded white panel would glare in a dark theme.
  std::fprintf(out, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"600\" "
                    "height=\"110\" viewBox=\"0 0 600 110\">\n");
  bar(out, "A", a, 20, "#4c9aff");
  bar(out, "B", b, 60, "#8f7ee7");
  std::fprintf(out, "</svg>\n");
  std::fclose(out);
  return 0;
}

#include <cstdio>

// Solution visualizer: draws the sum the reference answer holds, beside the two
// operands that produced it.
//
// Invoked as `vis <visualization.svg> <input.txt> <output.txt>`. Unlike the
// input visualizer this one needs argv[3], so it runs only once the answers
// exist -- which is why `rbx build` builds outputs before it visualizes.
//
// It exists to give the gallery a second cell per testcase. The manifest
// records the two channels separately (`visualization.input` and
// `visualization.output`), and having both populated is the only way to see
// that the panel keeps them apart.
int main(int argc, char *argv[]) {
  if (argc < 4) {
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

  FILE *ans = std::fopen(argv[3], "r");
  if (ans == nullptr) {
    return 1;
  }
  long long sum = 0;
  if (std::fscanf(ans, "%lld", &sum) != 1) {
    std::fclose(ans);
    return 1;
  }
  std::fclose(ans);

  FILE *out = std::fopen(argv[1], "w");
  if (out == nullptr) {
    return 1;
  }

  // The overflow the `big` group exists to catch is visible here: a sum that
  // does not fit in 32 bits is drawn in red, so the testcases that discriminate
  // between the good and the broken solutions are the ones that stand out in
  // the gallery.
  const char *fill = (sum > 2147483647LL || sum < -2147483648LL) ? "#e5534b"
                                                                 : "#57ab5a";

  std::fprintf(out, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"600\" "
                    "height=\"90\" viewBox=\"0 0 600 90\">\n");
  std::fprintf(out,
               "  <text x=\"16\" y=\"34\" font-family=\"monospace\" "
               "font-size=\"14\" fill=\"#888\">%lld + %lld =</text>\n",
               a, b);
  std::fprintf(out,
               "  <text x=\"16\" y=\"68\" font-family=\"monospace\" "
               "font-size=\"22\" fill=\"%s\">%lld</text>\n",
               fill, sum);
  std::fprintf(out, "</svg>\n");
  std::fclose(out);
  return 0;
}

// Grader helpers, public flavour: what contestants compile against. The judge
// flavour checks the hidden test header and frames the output with secrets;
// here every helper is a no-op, so a public grader reads the plain input and
// prints the plain answer.
namespace rbx {
namespace grader {

enum class Verdict { WA, PV };

[[noreturn]] inline void verdict(Verdict kind, const std::string &message) {
  std::fprintf(stderr, "%s: %s\n",
               kind == Verdict::WA ? "Wrong Answer" : "Protocol Violation",
               message.c_str());
  std::exit(0);
}

inline void start() {}

// Reopened on /dev/null rather than closed: reading a closed stdin is undefined
// behaviour, while this way contestant code that reads it just sees EOF.
inline void close_input() {
  if (std::freopen("/dev/null", "r", stdin) == nullptr) {
    std::fclose(stdin);
  }
}

inline void before_call() {}

inline void after_call() {}

} // namespace grader
} // namespace rbx

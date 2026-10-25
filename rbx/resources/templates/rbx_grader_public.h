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

// The convenient way to write a grader:
//
//   rbx::grader::Grader grader;        // reads and checks the hidden header
//   ... read the input ...
//   auto r = grader.run([&] {          // closes stdin, frames the calls
//     auto r = contestant_function(...);
//     if (bad(r)) grader.wrong_answer("why");   // judge-only checks go here
//     return r;
//   });                                // prints the closing secret and OK
//   ... print the answer ...
//
// The functions above remain available for graders that need finer control.
class Grader {
public:
  Grader() { start(); }

  Grader(const Grader &) = delete;
  Grader &operator=(const Grader &) = delete;

  // Runs `calls` -- the part where contestant code runs -- and returns what it
  // returns. Verdicts must be given inside it: once it returns, the run is OK.
  template <typename F> decltype(auto) run(F &&calls) {
    close_input();
    before_call();
    if constexpr (std::is_void_v<std::invoke_result_t<F>>) {
      std::forward<F>(calls)();
      after_call();
    } else {
      auto result = std::forward<F>(calls)();
      after_call();
      return result;
    }
  }

  [[noreturn]] void wrong_answer(const std::string &message) {
    verdict(Verdict::WA, message);
  }

  [[noreturn]] void protocol_violation(const std::string &message) {
    verdict(Verdict::PV, message);
  }
};

} // namespace grader
} // namespace rbx

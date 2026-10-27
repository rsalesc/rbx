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

inline void close_input() {
  if (std::freopen("/dev/null", "r", stdin) == nullptr) {
    std::fclose(stdin);
  }
}

inline void before_call() {}

inline void after_call() {}

class Grader {
public:
  Grader() { start(); }

  Grader(const Grader &) = delete;
  Grader &operator=(const Grader &) = delete;

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

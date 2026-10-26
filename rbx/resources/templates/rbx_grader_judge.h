namespace rbx {
namespace secrets {
inline constexpr const char *kInput = "{{INPUT_SECRET}}";
inline constexpr const char *kOutput = "{{OUTPUT_SECRET}}";
inline constexpr const char *kOutputEnd = "{{OUTPUT_END_SECRET}}";
} // namespace secrets

namespace grader {

enum class Verdict { WA, PV };

namespace detail {

inline int &stage() {
  static int value = 0;
  return value;
}

inline std::string readLine(std::FILE *file) {
  std::string line;
  int ch;
  while ((ch = std::fgetc(file)) != EOF && ch != '\n') {
    line.push_back(static_cast<char>(ch));
  }
  if (!line.empty() && line.back() == '\r') {
    line.pop_back();
  }
  return line;
}

} // namespace detail

[[noreturn]] inline void verdict(Verdict kind, const std::string &message) {
  if (detail::stage() >= 2) {
    std::fprintf(stderr, "rbx: grader verdict() called after after_call()\n");
    std::abort();
  }
  if (detail::stage() == 0) {
    std::printf("%s\n", secrets::kOutput);
  }
  std::printf("%s\n%s\n%s\n", secrets::kOutputEnd,
              kind == Verdict::WA ? "WA" : "PV", message.c_str());
  std::fflush(stdout);
  std::exit(0);
}

inline void start() {
  if (detail::readLine(stdin) != secrets::kInput) {
    verdict(Verdict::PV, "Possible tampering with the input");
  }
  ::rbx::detail::headerGroup() = detail::readLine(stdin);
}

inline void close_input() {
  if (std::freopen("/dev/null", "r", stdin) == nullptr) {
    std::fclose(stdin);
  }
}

inline void before_call() {
  std::printf("%s\n", secrets::kOutput);
  std::fflush(stdout);
  detail::stage() = 1;
}

inline void after_call() {
  std::printf("%s\nOK\n", secrets::kOutputEnd);
  detail::stage() = 2;
}

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

#ifdef _TESTLIB_H_
namespace rbx {
namespace grader {
namespace detail {

inline void consumeInputHeader() {
  if (inf.readLine() != secrets::kInput) {
    quitf(_fail, "rbx: the test input does not carry the grader header");
  }
  ::rbx::detail::headerGroup() = inf.readLine();
}

inline void consumePrologue(InStream &stream, bool isAnswer) {
  auto fail = [&](const std::string &message) {
    if (isAnswer) {
      quitf(_fail, "rbx: bad grader prologue in the answer: %s",
            message.c_str());
    }
    quitf(_wa, "Protocol violation: %s", message.c_str());
  };
  if (stream.eof() || stream.readLine() != secrets::kOutput) {
    fail("possible tampering with the output");
  }
  if (stream.eof() || stream.readLine() != secrets::kOutputEnd) {
    fail("the solution wrote to standard output or terminated the grader");
  }
  std::string status = stream.eof() ? std::string() : stream.readLine();
  if (status == "OK") {
    return;
  }
  std::string message = stream.eof() ? std::string() : stream.readLine();
  if (isAnswer) {
    quitf(_fail, "rbx: the answer was produced with grader status %s: %s",
          status.c_str(), message.c_str());
  }
  if (status == "WA") {
    quitf(_wa, "%s", message.c_str());
  }
  if (status == "PV") {
    quitf(_wa, "Protocol violation: %s", message.c_str());
  }
  quitf(_fail, "rbx: unknown grader status '%s'", status.c_str());
}

} // namespace detail
} // namespace grader

inline void registerGraderChecker(int argc, char *argv[]) {
  registerTestlibCmd(argc, argv);
  grader::detail::consumeInputHeader();
  grader::detail::consumePrologue(ans, true);
  grader::detail::consumePrologue(ouf, false);
}

inline void registerGraderInteraction(int argc, char *argv[]) {
  registerInteraction(argc, argv);
  grader::detail::consumeInputHeader();
}

} // namespace rbx
#endif

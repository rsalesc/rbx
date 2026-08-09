#ifndef _RBX_H
#define _RBX_H
#include <cstdint>
#include <cstdio>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#if defined(__APPLE__)
#include <crt_externs.h>
#elif defined(_WIN32)
// Not <cstdlib>: __argc/__argv are non-standard names in the global namespace,
// which <cstdlib> is not specified to declare.
#include <stdlib.h>
#endif

namespace rbx {
namespace detail {

// Splits the NUL-separated command line Linux exposes in /proc/self/cmdline.
// A trailing NUL terminates the last argument rather than introducing an empty
// one; an argument that is genuinely empty still yields an empty string.
// Kept out of the platform branch below so that it is testable everywhere.
inline std::vector<std::string> splitCmdline(const std::string &blob) {
  std::vector<std::string> args;
  std::string current;
  for (char ch : blob) {
    if (ch == '\0') {
      args.push_back(current);
      current.clear();
      continue;
    }
    current.push_back(ch);
  }
  if (!current.empty()) {
    args.push_back(current);
  }
  return args;
}

// Reads this process' own command line, so that the group can be resolved
// without the program having to call anything from main(), and without this
// header depending on any other library.
//
// Every supported platform exposes the command line to the process itself:
// macOS through the public _NSGetArgc/_NSGetArgv accessors, Linux through the
// NUL-separated /proc/self/cmdline, and Windows through the __argc/__argv
// globals the C runtime fills in at startup. Anywhere else this returns
// nothing, which reads as "no group" and falls back to package-level values.
//
// A deliberate non-solution: capturing argv from an __attribute__((constructor))
// hook taking (argc, argv, envp). GCC at -O2 folds such a hook into the
// translation unit's static-init thunk, which takes no arguments, so the
// values are silently lost. See the design doc for the full evidence.
inline std::vector<std::string> collectArgs() {
  std::vector<std::string> args;
#if defined(__APPLE__)
  int argc = *_NSGetArgc();
  char **argv = *_NSGetArgv();
  if (argv == nullptr) {
    return args;
  }
  for (int i = 0; i < argc && argv[i] != nullptr; i++) {
    args.push_back(std::string(argv[i]));
  }
#elif defined(__linux__)
  std::FILE *file = std::fopen("/proc/self/cmdline", "rb");
  if (file == nullptr) {
    return args;
  }
  std::string blob;
  int ch;
  while ((ch = std::fgetc(file)) != EOF) {
    blob.push_back(static_cast<char>(ch));
  }
  std::fclose(file);
  args = splitCmdline(blob);
#elif defined(_WIN32)
  // UNVERIFIED ON WINDOWS: no toolchain was available to test this branch.
  // The mechanism is the __argc/__argv globals declared by <stdlib.h>, which
  // both MinGW-w64 and MSVC populate at startup for programs entered through
  // main(). __argv is null in a wmain() build (__wargv carries the arguments
  // there instead), which the guard below degrades to "no group".
  if (__argv == nullptr) {
    return args;
  }
  for (int i = 0; i < __argc && __argv[i] != nullptr; i++) {
    args.push_back(std::string(__argv[i]));
  }
#endif
  return args;
}

inline std::string parseGroupFromArgs(const std::vector<std::string> &args) {
  static constexpr std::string_view kFlag = "--group";
  // Skips args[0], the program name.
  for (std::size_t i = 1; i < args.size(); i++) {
    const std::string &arg = args[i];
    if (arg.compare(0, kFlag.size(), kFlag) != 0) {
      continue;
    }
    // "--group=value"
    if (arg.size() > kFlag.size() && arg[kFlag.size()] == '=') {
      return arg.substr(kFlag.size() + 1);
    }
    // "--group value"; a trailing flag with no value reads as absent.
    if (arg.size() == kFlag.size()) {
      if (i + 1 < args.size()) {
        return args[i + 1];
      }
      return "";
    }
    // Anything else ("--groups", ...) is a different flag.
  }
  return "";
}

} // namespace detail

// The test group currently being validated, as passed by rbx via `--group`.
// Empty when the program was not run for a specific group, in which case
// getVar returns the package-level values.
//
// Parsed once, on first use.
inline const std::string &getGroup() {
  static const std::string group =
      detail::parseGroupFromArgs(detail::collectArgs());
  return group;
}

} // namespace rbx

std::optional<std::string> getStringVar(std::string name) {
  //<rbx::string_var>
  return std::nullopt;
}

std::optional<int64_t> getIntVar(std::string name) {
  //<rbx::int_var>
  return std::nullopt;
}

std::optional<float> getFloatVar(std::string name) {
  //<rbx::float_var>
  return std::nullopt;
}

std::optional<bool> getBoolVar(std::string name) {
  //<rbx::bool_var>
  return std::nullopt;
}

namespace rbx {
namespace vars {

template <typename T> T getVar(std::string name);

template <> int32_t getVar<int32_t>(std::string name) {
  auto opt = getIntVar(name);
  if (!opt.has_value()) {
    throw std::runtime_error("Variable " + name +
                             " is not an integer or could not be found");
  }
  if (opt.value() < std::numeric_limits<int32_t>::min() ||
      opt.value() > std::numeric_limits<int32_t>::max()) {
    throw std::runtime_error("Variable " + name + " of value " +
                             std::to_string(opt.value()) +
                             " does not fit in int32_t");
  }
  return opt.value();
}

template <> uint32_t getVar<uint32_t>(std::string name) {
  auto opt = getIntVar(name);
  if (!opt.has_value()) {
    throw std::runtime_error("Variable " + name +
                             " is not an integer or could not be found");
  }
  if (opt.value() < std::numeric_limits<uint32_t>::min() ||
      opt.value() > std::numeric_limits<uint32_t>::max()) {
    throw std::runtime_error("Variable " + name + " of value " +
                             std::to_string(opt.value()) +
                             " does not fit in uint32_t");
  }
  return opt.value();
}

template <> int64_t getVar<int64_t>(std::string name) {
  auto opt = getIntVar(name);
  if (!opt.has_value()) {
    throw std::runtime_error("Variable " + name +
                             " is not an integer or could not be found");
  }
  return opt.value();
}

template <> uint64_t getVar<uint64_t>(std::string name) {
  auto opt = getIntVar(name);
  if (!opt.has_value()) {
    throw std::runtime_error("Variable " + name +
                             " is not an integer or could not be found");
  }
  return opt.value();
}

template <> float getVar<float>(std::string name) {
  auto opt = getFloatVar(name);
  if (!opt.has_value()) {
    auto intOpt = getIntVar(name);
    if (intOpt.has_value()) {
      opt = (float)intOpt.value();
    }
  }
  if (!opt.has_value()) {
    throw std::runtime_error("Variable " + name +
                             " is not a float or could not be found");
  }
  return opt.value();
}

template <> double getVar<double>(std::string name) {
  return getVar<float>(name);
}

template <> std::string getVar<std::string>(std::string name) {
  auto opt = getStringVar(name);
  if (!opt.has_value()) {
    auto intOpt = getIntVar(name);
    if (intOpt.has_value()) {
      opt = std::to_string(intOpt.value());
    }
  }
  if (!opt.has_value()) {
    auto floatOpt = getFloatVar(name);
    if (floatOpt.has_value()) {
      opt = std::to_string(floatOpt.value());
    }
  }
  if (!opt.has_value()) {
    throw std::runtime_error("Variable " + name +
                             " is not a string or could not be found");
  }
  return opt.value();
}

template <> bool getVar<bool>(std::string name) {
  auto opt = getBoolVar(name);
  if (!opt.has_value()) {
    opt = getIntVar(name) != 0;
  }
  if (!opt.has_value()) {
    throw std::runtime_error("Variable " + name +
                             " is not a boolean or could not be found");
  }
  return opt.value();
}

inline void joinVarPath(std::string &acc) { (void)acc; }

template <typename... Args>
void joinVarPath(std::string &acc, const std::string &part,
                 const Args &...rest) {
  if (!acc.empty() && !part.empty()) {
    acc += '.';
  }
  acc += part;
  joinVarPath(acc, rest...);
}

} // namespace vars
} // namespace rbx

// Reads a variable declared in the `vars` section of the package.
//
// The path to the variable can be given either as a single dotted string or as
// one segment per argument, so the two calls below are equivalent:
//
//   getVar<int>("N.max");
//   getVar<int>("N", "max");
//
// Supported types are int32_t, uint32_t, int64_t, uint64_t, float, double,
// std::string and bool.
template <typename T, typename... Args>
T getVar(const std::string &first, const Args &...rest) {
  std::string name;
  rbx::vars::joinVarPath(name, first, rest...);
  return rbx::vars::getVar<T>(name);
}
#endif

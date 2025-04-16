#include <optional>
#include <stdexcept>
#include <string>

#ifndef _RBX_H
#define _RBX_H

std::optional<std::string> getStringVar(std::string name) {
  //<rbx::string_var>
  return std::nullopt;
}

std::optional<int> getIntVar(std::string name) {
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

template <typename T> T getVar(std::string name);

template <> int getVar<int>(std::string name) {
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
#endif

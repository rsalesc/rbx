/*
 * Copyright (c) 2026 Bruno Monteiro
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

#pragma once

#include <algorithm>
#include <functional>
#include <iomanip>
#include <iostream>
#include <map>
#include <optional>
#include <queue>
#include <random>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/types.h>
#include <type_traits>
#include <utility>
#include <vector>

namespace tgen {

/**************************
 *                        *
 *   GENERAL OPERATIONS   *
 *                        *
 **************************/

namespace detail {

// Type aliases.
using u128 = unsigned __int128;
using i128 = __int128;

/*
 * Error handling.
 */

inline void throw_assertion_error(const std::string &condition,
								  const std::string &msg, const char *file,
								  int line) {
	throw std::runtime_error("tgen: " + msg + " (assertion `" + condition +
							 "` failed at " + file + ":" +
							 std::to_string(line) + ")");
}
inline void throw_assertion_error(const std::string &condition,
								  const char *file, int line) {
	throw std::runtime_error("tgen: assertion `" + condition + "` failed at " +
							 std::string(file) + ":" + std::to_string(line));
}
inline std::runtime_error error(const std::string &msg) {
	return std::runtime_error("tgen: " + msg);
}
inline std::runtime_error contradiction_error(const std::string &type,
											  const std::string &msg = "") {
	// Tried to generate a contradicting type.
	std::string error_msg =
		type + ": invalid " + type + " (contradicting restrictions)";
	if (!msg.empty())
		error_msg += ": " + msg;
	return error(error_msg);
}
inline std::runtime_error
complex_restrictions_error(const std::string &type,
						   const std::string &msg = "") {
	// Tried to generate a type with too many distinct restrictions.
	std::string error_msg =
		type + ": cannot represent " + type + " (complex restrictions)";
	if (!msg.empty())
		error_msg += ": " + msg;
	return error(error_msg);
}
inline void tgen_ensure_against_bug(bool cond, const std::string &msg = "") {
	if (!cond) {
		std::string error_msg;
		if (!msg.empty())
			error_msg = "tgen: " + msg + "\n";
		error_msg += "tgen: THERE IS A BUG IN TGEN; PLEASE CONTACT MAINTAINERS";
		throw std::runtime_error(error_msg);
	}
}

// Ensures condition is true, with nice debug.
#define tgen_ensure(cond, ...)                                                 \
	if (!(cond))                                                               \
	tgen::detail::throw_assertion_error(#cond, ##__VA_ARGS__, __FILE__,        \
										__LINE__)

// Registering checks.
inline bool registered = false;
inline void ensure_registered() {
	tgen_ensure(registered,
				"tgen was not registered! You should call "
				"tgen::register_gen(argc, argv) before running tgen functions");
}

// Template magic to detect types in compile time.

// Detects containers != std::string.
template <typename T, typename = void> struct is_container : std::false_type {};
template <typename T>
struct is_container<T,
					std::void_t<typename std::remove_reference_t<T>::value_type,
								decltype(std::begin(std::declval<T>())),
								decltype(std::end(std::declval<T>()))>>
	: std::true_type {};
// Exclude all basic_string variants
template <typename Char, typename Traits, typename Alloc>
struct is_container<std::basic_string<Char, Traits, Alloc>> : std::false_type {
};
template <typename Char, typename Traits, typename Alloc>
struct is_container<const std::basic_string<Char, Traits, Alloc>>
	: std::false_type {};
template <typename Char, typename Traits, typename Alloc>
struct is_container<std::basic_string<Char, Traits, Alloc> &>
	: std::false_type {};
template <typename Char, typename Traits, typename Alloc>
struct is_container<const std::basic_string<Char, Traits, Alloc> &>
	: std::false_type {};

// Detects std::pair.
template <typename T> struct is_pair : std::false_type {};
template <typename A, typename B>
struct is_pair<std::pair<A, B>> : std::true_type {};
// Detects std::tuple.
template <typename T> struct is_tuple : std::false_type {};
template <typename... Ts>
struct is_tuple<std::tuple<Ts...>> : std::true_type {};
// Detects scalar (printed atomically).
template <typename T>
struct is_scalar
	: std::bool_constant<!is_container<T>::value and !is_tuple<T>::value and
						 !is_pair<T>::value> {};
// Detects complex container.
template <typename T>
struct is_container_multiline
	: std::bool_constant<is_container<T>::value and
						 !is_scalar<typename std::remove_cv_t<
							 std::remove_reference_t<T>>::value_type>::value> {
};
// Detects complex std::pair.
template <typename T> struct is_pair_multiline : std::false_type {};
template <typename A, typename B>
struct is_pair_multiline<std::pair<A, B>>
	: std::bool_constant<!is_scalar<A>::value or !is_scalar<B>::value> {};
// Detects complex std::tuple.
template <typename Tuple> struct is_tuple_multiline : std::false_type {};
template <typename... Ts>
struct is_tuple_multiline<std::tuple<Ts...>>
	: std::bool_constant<(!is_scalar<Ts>::value or ...)> {};

// Used to return false in compile time only if evaluated.
template <typename> inline constexpr bool dependent_false_v = false;

/*
 * Properties of custom types.
 */

// If type is sequential (list-like).
using is_sequential_tag = void;

// If it makes sense to have a subset of the type.
using has_subset_defined_tag = void;

/*
 * Unique rng to use.
 */

// The single rng to be used by the library.
inline std::mt19937 rng;

/*
 * C++ version types.
 */

// Global C++ version value (0 means unknown).
struct cpp_value {
	int version_;

	cpp_value(std::optional<int> version = std::nullopt)
		: version_(version ? *version : 0) {
		if (version) {
			tgen_ensure(*version == 17 or *version == 20 or *version == 23,
						"unsupported C++ version (use 17, 20, 23)");
		}
	}
};
inline cpp_value cpp;

/*
 * Compiler types.
 */

// Kinds of compilers.
enum class compiler_kind { gcc, clang, unknown };

// Global compiler value.
struct compiler_value {
	compiler_kind kind_;
	int major_;
	int minor_;

	compiler_value(compiler_kind kind = compiler_kind::unknown, int major = 0,
				   int minor = 0)
		: kind_(kind), major_(major), minor_(minor) {}
};
inline compiler_value compiler;

/*
 * Printing.
 */

// Print view struct for printing either a container or a sequential generator
// element.
template <typename T,
		  bool IsCont = detail::is_container<std::decay_t<T>>::value>
struct print_cols_view;

// Container.
template <typename T> struct print_cols_view<T, true> {
	const T &value;
	decltype(std::begin(std::declval<const T &>())) it;

	print_cols_view(const T &v) : value(v), it(v.begin()) {}

	std::size_t size() const { return value.size(); }
	decltype(auto) get(std::size_t) const { return *it; }
	void advance() { ++it; }
};

// Sequential generator element.
template <typename T> struct print_cols_view<T, false> {
	const T &value;

	print_cols_view(const T &v) : value(v) {}

	std::size_t size() const { return value.size(); }
	decltype(auto) get(std::size_t i) const { return value[i]; }
	void advance() {}
};

} // namespace detail

/*
 * Base classes.
 */

// Needed for return type of some functions.
template <typename T> struct list;

// Generates distinct values of a function.
template <typename Func, typename... Args> struct distinct {
	Func func_;
	std::tuple<Args...> args_;
	using T = std::invoke_result_t<Func &, Args &...>;
	std::set<T> seen_;

	distinct(Func func, Args... args)
		: func_(std::move(func)), args_(std::move(args)...) {}

	// Generates distinct value and inserts it if `insert` is true.
	// Returns the value if found, otherwise returns std::nullopt.
	auto generate_distinct(bool insert) {
		for (int i = 0; i < 84 * std::max<int>(1, seen_.size()); ++i) {
			T val = std::apply(func_, args_);
			if (insert ? seen_.insert(val).second : seen_.count(val) == 0)
				return std::optional<T>(val);
		}

		// Not found.
		return std::optional<T>();
	}

	// Generates a distinct value (i.e., one not returned before).
	//
	// Assume gen() produces a uniformly random value in O(T) time.
	// Since duplicates are rejected, the expected number of trials over
	// k successful generations is:
	//
	//   sum_{i=1}^k k / i = O(k log k)
	//
	// (coupon collector argument).
	//
	// Each trial additionally performs O(log k) work to check/store
	// previously generated values, yielding a total time of
	// O((T + log k) * k log k).
	//
	// Thus, the amortized expected time per call is
	// O(T * log k + log^2 k).
	//
	// With extremely small probability (< 1e-18), the algorithm may
	// incorrectly report that no more distinct values exist.
	auto gen() {
		auto val = generate_distinct(true);
		if (val)
			return *val;

		throw detail::error("distinct: no more distinct values");
	}
	template <typename U> auto gen(std::initializer_list<U> il) {
		return gen(std::vector<U>(il));
	}

	// Generates a list of distinct values.
	auto gen_list(int size) {
		std::vector<T> res;
		for (int i = 0; i < size; ++i)
			res.push_back(gen());

		return typename list<T>::value(res);
	}

	// Checks if there are no more distinct values.
	// With extremely small probability (< 1e-18), the algorithm may
	// incorrectly report that there are no more distinct values.
	bool empty() { return generate_distinct(false) == std::nullopt; }

	// Generates all distinct values.
	auto gen_all() {
		std::vector<T> res;
		while (true) {
			auto val = generate_distinct(true);
			if (val)
				res.push_back(*val);
			else
				break;
		}
		return typename list<T>::value(res);
	}

	// Nice error for `out << distinct`.
	friend std::ostream &operator<<(std::ostream &out, const distinct &) {
		static_assert(
			detail::dependent_false_v<distinct>,
			"distinct: cannot print a distinct generator. Maybe you forgot to "
			"call `gen()`?");
		return out;
	}
};
template <typename Func, typename... Args>
distinct(Func, Args...) -> distinct<Func, Args...>;

// Base struct for generators.
template <typename Gen> struct gen_base {
	const Gen &self() const { return *static_cast<const Gen *>(this); }

	template <typename... Args> auto gen_list(int size, Args &&...args) const {
		std::vector<typename Gen::value> res;

		for (int i = 0; i < size; ++i)
			res.push_back(static_cast<const Gen *>(this)->gen(
				std::forward<Args>(args)...));

		return typename list<typename Gen::value>::value(res);
	}

	// Calls the generator until predicate is true.
	template <typename Pred, typename... Args>
	auto gen_until(Pred predicate, int max_tries, Args &&...args) const {
		for (int i = 0; i < max_tries; ++i) {
			typename Gen::value val = static_cast<const Gen *>(this)->gen(
				std::forward<Args>(args)...);

			if (predicate(val))
				return val;
		}

		throw detail::error("could not generate value matching predicate");
	}
	template <typename Pred, typename T, typename... Args>
	auto gen_until(Pred predicate, int max_tries, std::initializer_list<T> il,
				   Args &&...args) const {
		return gen_until(predicate, max_tries, std::vector<T>(il),
						 std::forward<Args>(args)...);
	}

	// Distinct for generator.
	template <typename... Args> auto distinct(Args &&...args) const {
		return tgen::distinct(
			[self = self()](auto &&...inner_args) mutable -> decltype(auto) {
				return self.gen(
					std::forward<decltype(inner_args)>(inner_args)...);
			},
			std::forward<Args>(args)...);
	}
	template <typename T, typename... Args>
	auto distinct(std::initializer_list<T> il, Args &&...args) const {
		return distinct(std::vector<T>(il), std::forward<Args>(args)...);
	}

	// Nice error for `out << generator`.
	friend std::ostream &operator<<(std::ostream &out, const gen_base &) {
		static_assert(detail::dependent_false_v<gen_base>,
					  "gen_base: cannot print a generator. Maybe you forgot to "
					  "call `gen()`?");
		return out;
	}
};

// Base class for generator values.
template <typename Val> struct gen_value_base {
	const Val &self() const { return *static_cast<const Val *>(this); }

	bool operator<(const Val &rhs) const {
		return self().to_std() < rhs.to_std();
	}
};

/*
 * Type compile-time detection.
 */

// Detects associative containers.
template <typename T, typename = void>
struct is_associative_container : std::false_type {};
template <typename T>
struct is_associative_container<
	T, std::void_t<typename T::key_type, typename T::key_compare>>
	: std::true_type {};

// Detects generator values.
template <typename T>
struct is_generator_value
	: std::is_base_of<gen_value_base<std::decay_t<T>>, std::decay_t<T>> {};

// Detects sequential generator values.
template <typename T, typename = void>
struct is_sequential : std::false_type {};
template <typename T>
struct is_sequential<
	T, std::void_t<typename std::decay_t<T>::tgen_is_sequential_tag>>
	: std::true_type {};

// Detects generator values with defined subset.
template <typename T, typename = void>
struct has_subset_defined : std::false_type {};
template <typename T>
struct has_subset_defined<
	T, std::void_t<typename std::decay_t<T>::tgen_has_subset_defined_tag>>
	: std::true_type {};

/*
 * Easier printing.
 */

// Struct to print standard types to std::ostream;
struct print {
	std::string s_;

	template <typename T> print(const T &val, char sep = ' ') {
		std::ostringstream oss;
		write(oss, val, sep);
		s_ = oss.str();
	}
	template <typename T>
	print(const std::initializer_list<T> &il, char sep = ' ') {
		std::ostringstream oss;
		write(oss, std::vector<T>(il), sep);
		s_ = oss.str();
	}
	template <typename T>
	print(const std::initializer_list<std::initializer_list<T>> &il,
		  char sep = ' ') {
		std::ostringstream oss;
		std::vector<std::vector<T>> mat;
		for (const auto &i : il)
			mat.push_back(i);
		write(oss, mat, sep);
		s_ = oss.str();
	}

	template <typename T> void write(std::ostream &os, const T &val, char sep) {
		if constexpr (detail::is_pair<T>::value) {
			if constexpr (detail::is_pair_multiline<T>::value) {
				write(os, val.first, sep);
				os << '\n';
				write(os, val.second, sep);
			} else {
				// Use space for inner separator.
				write(os, val.first, ' ');
				os << sep;
				write(os, val.second, ' ');
			}
		} else if constexpr (detail::is_tuple<T>::value)
			write_tuple(os, val, sep);
		else if constexpr (detail::is_container<T>::value)
			write_container(os, val, sep);
		else if constexpr (std::is_same_v<T, detail::i128> or
						   std::is_same_v<T, detail::u128>)
			write_128_number(os, val);
		else
			os << val;
	}

	// Writes 128 bit number.
	template <typename T> void write_128_number(std::ostream &os, T num) {
		static const long long BASE = 1e18;

		if (num < 0) {
			os << '-';
			num = -num;
		}

		if (num >= BASE) {
			write_128_number(os, num / BASE);
			os << std::setw(18) << std::setfill('0')
			   << static_cast<long long>(num % BASE);
		} else
			os << static_cast<long long>(num);
	}
	// Writes container, checking separator.
	template <typename C>
	void write_container(std::ostream &os, const C &container, char sep) {
		bool first = true;

		for (const auto &e : container) {
			if (!first)
				os << (detail::is_container_multiline<C>::value ? '\n' : sep);
			first = false;
			write(os, e, detail::is_container_multiline<C>::value ? sep : ' ');
		}
	}

	// Writes tuple, checking separator.
	template <typename Tuple, size_t... I>
	void write_tuple_impl(std::ostream &os, const Tuple &tp, char sep,
						  std::index_sequence<I...>) {
		bool first = true;
		((os << (first ? (first = false, "")
					   : (detail::is_tuple_multiline<Tuple>::value
							  ? "\n"
							  : std::string(1, sep))),
		  write(os, std::get<I>(tp),
				detail::is_tuple_multiline<Tuple>::value ? sep : ' ')),
		 ...);
	}
	template <typename T>
	void write_tuple(std::ostream &os, const T &tp, char sep) {
		write_tuple_impl(os, tp, sep,
						 std::make_index_sequence<std::tuple_size<T>::value>{});
	}

	friend std::ostream &operator<<(std::ostream &out, const print &pr) {
		return out << pr.s_;
	}
};

// Prints in a new line.
struct println : print {
	template <typename T>
	println(const T &val, char sep = ' ') : print(val, sep) {}
	template <typename T>
	println(const std::initializer_list<T> &il, char sep = ' ')
		: print(il, sep) {}
	template <typename T>
	println(const std::initializer_list<std::initializer_list<T>> &il,
			char sep = ' ')
		: print(il, sep) {}

	friend std::ostream &operator<<(std::ostream &out, const println &pr) {
		return out << pr.s_ << '\n';
	}
};

// Prints container / sequential generator value on its own column.
// Example:
//   A = {1, 2, 3}, B = {4, 2, 5}
//   print_each(A, B) will print:
//  "1 4
//   2 2
//   3 5
//",
//  that is, ir prints the end of the line for all lines.
template <typename... Args> struct print_cols {
	std::string s_;

	template <
		std::enable_if_t<((detail::is_container<std::decay_t<Args>>::value or
						   is_sequential<std::decay_t<Args>>::value) and
						  ...),
						 int> = 0>
	print_cols(const Args &...args) {
		std::ostringstream oss;
		write(oss, args...);
		s_ = oss.str();
	}

	void write(std::ostream &os, const Args &...args) {
		auto views = std::apply(
			[](const Args &...inner_args) {
				return std::make_tuple(
					detail::print_cols_view<decltype(inner_args)>{
						inner_args}...);
			},
			std::forward_as_tuple(args...));

		const std::size_t n = std::get<0>(views).size();

		auto check = [&](const auto &v) {
			tgen_ensure(v.size() == n, "print_cols: sizes should be the same");
		};
		std::apply([&](const auto &...v) { (check(v), ...); }, views);

		for (std::size_t i = 0; i < n; ++i) {
			bool first = true;

			std::apply(
				[&](const auto &...v) {
					((os << (first ? "" : " ") << print(v.get(i)),
					  first = false),
					 ...);
				},
				views);

			os << '\n';

			std::apply([](auto &...v) { (v.advance(), ...); }, views);
		}
	}

	friend std::ostream &operator<<(std::ostream &out, const print_cols &pr) {
		return out << pr.s_;
	}
};

/*
 * Global random operations.
 */

// Returns a uniformly random number in [0, right)
// O(1).
template <typename T> T next(T right) {
	detail::ensure_registered();
	if constexpr (std::is_integral_v<T>) {
		tgen_ensure(right >= 1, "value for `next` must be valid");
		return std::uniform_int_distribution<T>(0, right - 1)(detail::rng);
	} else if constexpr (std::is_floating_point_v<T>) {
		tgen_ensure(right >= 0, "value for `next` must be valid");
		return std::uniform_real_distribution<T>(0, right)(detail::rng);
	} else
		throw detail::error("invalid type for next (" +
							std::string(typeid(T).name()) + ")");
}

// Returns a uniformly random number in [left, right].
// O(1).
template <typename T> T next(T left, T right) {
	detail::ensure_registered();
	tgen_ensure(left <= right, "range for `next` must be valid");
	if constexpr (std::is_integral_v<T>)
		return std::uniform_int_distribution<T>(left, right)(detail::rng);
	else if constexpr (std::is_floating_point_v<T>)
		return std::uniform_real_distribution<T>(left, right)(detail::rng);
	else
		throw detail::error("invalid type for next (" +
							std::string(typeid(T).name()) + ")");
}

// Skewed next.
//
// Returns a random number in [0, right) with a bias controlled by `w`.
// - w = 0:
//     Uniform distribution.
// - w > 0:
//     Returns the maximum of (w + 1) independent uniform samples.
//     Biases the distribution toward larger values.
//     The resulting density is proportional to:
//         f(x) = x^w
//     In particular:
//         w = 1 -> linear bias
//         w = 2 -> quadratic bias
//         w = 3 -> cubic bias
// - w < 0:
//     Returns the minimum of (-w + 1) independent uniform samples.
//     Symmetric to the w > 0 case.
// The continuous version corresponds to Beta distributions:
//     w > 0 -> Beta(w + 1, 1)
//     w < 0 -> Beta(1, -w + 1)
// For |w| > 5, the distribution is approximate.
// O(1).
template <typename T> T wnext(T right, int w) {
	// For small |w|, use the naive approach.
	if (abs(w) <= 5) {
		T val = next<T>(right);
		for (int i = 0; i < w; ++i)
			val = std::max(val, next<T>(right));
		for (int i = 0; i < -w; ++i)
			val = std::min(val, next<T>(right));
		return val;
	}

	// O(1) way.
	double x, r = next<double>(0, 1);

	if (w >= 0) {
		x = std::pow(r, 1.0 / (w + 1));
	} else {
		x = 1.0 - std::pow(r, 1.0 / (-w + 1));
	}

	return T(x * right);
}

// Returns a random number in [left, right] with a bias controlled by `w`.
// O(1).
template <typename T> T wnext(T left, T right, int w) {
	// For small |w|, use the naive approach.
	if (abs(w) <= 5) {
		T val = next<T>(left, right);
		for (int i = 0; i < w; ++i)
			val = std::max(val, next<T>(left, right));
		for (int i = 0; i < -w; ++i)
			val = std::min(val, next<T>(left, right));
		return val;
	}

	// O(1) way.
	double x, r = next<double>(0, 1);

	if (w >= 0) {
		x = std::pow(r, 1.0 / (w + 1));
	} else {
		x = 1.0 - std::pow(r, 1.0 / (-w + 1));
	}

	return left + T(x * (right - left));
}

namespace detail {

// Uniformly random 128 bit number in [0, total).
// O(1) expected.
inline u128 next128(u128 total) {
	tgen_ensure(total > 0, "next128: total must be positive");

	// Largest multiple of total less than 2^128.
	u128 limit = (u128(-1) / total) * total;

	while (true) {
		// Generate uniform 128-bit random number.
		u128 r = (u128(next<uint64_t>(0, std::numeric_limits<uint64_t>::max()))
				  << 64) |
				 next<uint64_t>(0, std::numeric_limits<uint64_t>::max());

		if (r < limit)
			return r % total;
	}
}

} // namespace detail

// Weighted sampler.
//
// Generates indices with probability proportional to `distribution`, using
// alias method.
//
// Internally, integral weights are accumulated in unsigned __int128 (exact);
// floating-point weights are accumulated in double.
// <O(n), O(1)>.
template <typename T> struct weighted_sampler {
	static_assert(std::is_arithmetic_v<T>,
				  "weighted_sampler requires an arithmetic weight type");

	// Internal storage type: `u128` for integral inputs (exact arithmetic),
	// `double` for floating-point inputs.
	using storage_t =
		std::conditional_t<std::is_integral_v<T>, detail::u128, double>;

	int n_;
	std::vector<storage_t> weight_;
	std::vector<int> alias_;
	storage_t total_;

	// Creates an alias method for generating indices with probability
	// proportional to the distribution.
	// O(n).
	weighted_sampler(const std::vector<T> &distribution)
		: n_(distribution.size()), alias_(n_) {
		tgen_ensure(distribution.size() > 0,
					"weighted_sampler: distribution must be non-empty");
		for (const auto &w : distribution)
			tgen_ensure(w >= 0,
						"weighted_sampler: distribution must be non-negative");

		total_ = std::accumulate(distribution.begin(), distribution.end(),
								 storage_t(0));

		std::queue<int> big, small;
		for (int i = 0; i < n_; ++i) {
			weight_.push_back(storage_t(n_) * storage_t(distribution[i]));
			if (weight_[i] < total_)
				small.push(i);
			else
				big.push(i);
		}

		while (!small.empty() and !big.empty()) {
			int s = small.front();
			small.pop();
			int b = big.front();
			big.pop();

			alias_[s] = b;

			weight_[b] -= total_ - weight_[s];
			if (weight_[b] < total_)
				small.push(b);
			else
				big.push(b);
		}

		detail::tgen_ensure_against_bug(
			small.empty(), "weighted_sampler: small must be empty");

		// The remaining elements should have weight equal to total and be
		// assigned to themselves.
		while (!big.empty()) {
			int b = big.front();
			big.pop();
			if constexpr (std::is_integral_v<T>) {
				detail::tgen_ensure_against_bug(
					weight_[b] == total_,
					"weighted_sampler: weight of big element must be total");
			}
			alias_[b] = b;
		}
	}
	weighted_sampler(const std::initializer_list<T> &distribution)
		: weighted_sampler(std::vector<T>(distribution)) {}

	// Uniformly random value in [0, total). Overloaded so next() can dispatch
	// at compile time to the right primitive for the chosen `storage_t`.
	static detail::u128 sample_below(detail::u128 total) {
		return detail::next128(total);
	}
	static double sample_below(double total) {
		return tgen::next<double>(0, total);
	}

	// Generates a random index with probability proportional to the
	// distribution.
	// O(1).
	size_t next() const {
		int i = tgen::next<int>(0, n_ - 1);
		return sample_below(total_) < weight_[i] ? i : alias_[i];
	}
};
template <typename T>
weighted_sampler(const std::vector<T> &) -> weighted_sampler<T>;
template <typename T>
weighted_sampler(const std::initializer_list<T> &) -> weighted_sampler<T>;

// Returns i with probability proportional to distribution[i].
// O(|distribution|).
template <typename T>
size_t next_by_distribution(const std::vector<T> &distribution) {
	return weighted_sampler(distribution).next();
}
template <typename T>
size_t next_by_distribution(const std::initializer_list<T> &distribution) {
	return next_by_distribution(std::vector<T>(distribution));
}

// Returns a vector of k indices with probability proportional to
// `distribution`. Uses alias method.
// O(k + |distribution|).
template <typename T>
std::vector<int> many_by_distribution(int k,
									  const std::vector<T> &distribution) {
	tgen_ensure(distribution.size() > 0, "distribution must be non-empty");
	tgen_ensure(k >= 0, "number of elements to choose must be non-negative");

	weighted_sampler am(distribution);
	std::vector<int> res;
	for (int i = 0; i < k; ++i)
		res.push_back(am.next());
	return res;
}
template <typename T>
std::vector<int>
many_by_distribution(int k, const std::initializer_list<T> &distribution) {
	return many_by_distribution(k, std::vector<T>(distribution));
}

// Shuffles [first, last) inplace uniformly, for RandomAccessIterator.
// O(|container|).
template <typename It> void shuffle(It first, It last) {
	if (first == last)
		return;

	for (It i = first + 1; i != last; ++i)
		std::iter_swap(i, first + next(0, static_cast<int>(i - first)));
}

// Shuffles sequential generator value uniformly.
// O(|val|).
template <typename Val, std::enable_if_t<is_sequential<Val>::value, int> = 0>
void shuffle(Val &val) {
	for (int i = 0; i < val.size(); ++i)
		std::swap(val[i], val[next(0, val.size() - 1)]);
}

// Shuffles container uniformly.
// O(|container|).
template <typename C, std::enable_if_t<!is_generator_value<C>::value, int> = 0>
[[nodiscard]] auto shuffled(const C &container) {
	if constexpr (is_associative_container<C>::value) {
		std::vector<typename C::value_type> vec(container.begin(),
												container.end());
		shuffle(vec.begin(), vec.end());
		return vec;
	} else {
		auto new_container = container;
		shuffle(new_container.begin(), new_container.end());
		return new_container;
	}
}
template <typename T>
[[nodiscard]] std::vector<T> shuffled(const std::initializer_list<T> &il) {
	return shuffled(std::vector<T>(il));
}

// Shuffles sequential generator value uniformly.
// O(n).
template <typename Val, std::enable_if_t<is_sequential<Val>::value, int> = 0>
[[nodiscard]] Val shuffled(const Val &val) {
	Val new_val = val;
	shuffle(new_val);
	return new_val;
}

// Returns a random element from [first, last) uniformly.
// O(1) for random_access_iterator, O(|last - first|) otherwise.
template <typename It> typename It::value_type pick(It first, It last) {
	int size = std::distance(first, last);
	It it = first;
	std::advance(it, next(0, size - 1));
	return *it;
}

// Returns a random element from container uniformly.
// O(1) for random_access_iterator, O(|container|) otherwise.
template <typename C, std::enable_if_t<!is_generator_value<C>::value, int> = 0>
typename C::value_type pick(const C &container) {
	return pick(container.begin(), container.end());
}
template <typename T> T pick(const std::initializer_list<T> &il) {
	return pick(std::vector<T>(il));
}

// Returns a random element from sequential generator value uniformly.
// O(1).
template <typename Val, std::enable_if_t<is_sequential<Val>::value, int> = 0>
typename Val::value_type pick(const Val &val) {
	return val[next<int>(0, val.size() - 1)];
}

// Returns container[i] with probability proportional to distribution[i].
// O(1) for random_access_iterator, O(|container|) otherwise.
template <typename C, typename T,
		  std::enable_if_t<!is_generator_value<C>::value, int> = 0>
typename C::value_type pick_by_distribution(const C &container,
											std::vector<T> distribution) {
	tgen_ensure(container.size() == distribution.size(),
				"container and distribution must have the same size");
	auto it = container.begin();
	std::advance(it, next_by_distribution(distribution));
	return *it;
}
template <typename C, typename T,
		  std::enable_if_t<!is_generator_value<C>::value, int> = 0>
typename C::value_type
pick_by_distribution(const C &container,
					 const std::initializer_list<T> &distribution) {
	return pick_by_distribution(container, std::vector<T>(distribution));
}
template <typename T, typename U>
T pick_by_distribution(const std::initializer_list<T> &il,
					   const std::vector<U> &distribution) {
	return pick_by_distribution(std::vector<T>(il), distribution);
}
template <typename T, typename U>
T pick_by_distribution(const std::initializer_list<T> &il,
					   const std::initializer_list<U> &distribution) {
	return pick_by_distribution(std::vector<T>(il),
								std::vector<U>(distribution));
}

// Returns val[i] with probability proportional to distribution[i].
// O(1).
template <typename Val, typename T,
		  std::enable_if_t<is_sequential<Val>::value, int> = 0>
typename Val::value_type
pick_by_distribution(const Val &val, const std::vector<T> &distribution) {
	tgen_ensure(static_cast<size_t>(val.size()) == distribution.size(),
				"value and distribution must have the same size");
	return val[next_by_distribution(distribution)];
}
template <typename Val, typename T,
		  std::enable_if_t<is_sequential<Val>::value, int> = 0>
typename Val::value_type
pick_by_distribution(const Val &val,
					 const std::initializer_list<T> &distribution) {
	return pick_by_distribution(val, std::vector<T>(distribution));
}

// Chooses k values uniformly from container, as in a subsequence of size k.
// Returns a copy. O(|container|).
template <typename C, std::enable_if_t<!is_generator_value<C>::value, int> = 0>
C choose(const C &container, int k) {
	tgen_ensure(0 < k and k <= static_cast<int>(container.size()),
				"number of elements to choose must be valid");
	std::vector<typename C::value_type> new_vec;
	C new_container;
	int need = k, left = container.size();
	for (auto cur_it = container.begin(); cur_it != container.end(); ++cur_it) {
		if (next(1, left--) <= need) {
			new_container.insert(new_container.end(), *cur_it);
			need--;
		}
	}
	return new_container;
}
template <typename T>
std::vector<T> choose(const std::initializer_list<T> &il, int k) {
	return choose(std::vector<T>(il), k);
}

// Chooses k values uniformly from sequential generator value, as in a
// subsequence of size k.
// O(n).
template <typename Val, std::enable_if_t<is_sequential<Val>::value and
											 has_subset_defined<Val>::value,
										 int> = 0>
Val choose(const Val &val, int k) {
	tgen_ensure(0 < k and k <= static_cast<int>(val.size()),
				"number of elements to choose must be valid");
	std::vector<typename Val::value_type> new_vec;
	int need = k;
	for (int i = 0; need > 0; ++i) {
		int left = val.size() - i;
		if (next(1, left) <= need) {
			new_vec.push_back(val[i]);
			need--;
		}
	}
	return Val(new_vec);
}

// Number distinct generator for integral types.
template <typename T> struct distinct_range {
	T left_, right_;
	T num_available_;
	std::map<T, T> virtual_list_;

	// Generator of distinct values in [left, right].
	distinct_range(T left, T right)
		: left_(left), right_(right), num_available_(right - left + 1) {}

	// Returns the number of distinct values left to generate.
	T size() const { return num_available_; }

	// Generates a random value in [left_, right_] that has not been generated
	// yet. O(log n).
	T gen() {
		// One iteration of Fisher–Yates.
		tgen_ensure(size() > 0, "distinct_range: no more values to generate");

		T i = next<T>(0, size() - 1);
		T j = size() - 1;

		T vi = virtual_list_.count(i) ? virtual_list_[i] : i;
		T vj = virtual_list_.count(j) ? virtual_list_[j] : j;
		virtual_list_[i] = vj;

		--num_available_;

		return vi + left_;
	}

	// Generates a list of distict values.
	// O(size * log(n)).
	auto gen_list(int size) {
		std::vector<T> res;
		for (int i = 0; i < size; ++i)
			res.push_back(gen());
		return typename list<T>::value(res);
	}

	// Generates all distict values.
	// O(n log(n))
	auto gen_all() {
		std::vector<T> res;
		while (size() > 0)
			res.push_back(gen());
		return typename list<T>::value(res);
	}
};

// Distinct generator for containers.
template <typename T> struct distinct_container {
	std::vector<T> list_;
	distinct_range<size_t> idx_;

	// Creates a distinct container generator for the given container.
	template <typename C>
	distinct_container(const C &container)
		: list_(container.begin(), container.end()),
		  idx_(0, static_cast<int>(container.size()) - 1) {}
	distinct_container(const std::initializer_list<T> &il)
		: distinct_container(std::vector<T>(il)) {}

	// Returns the number of distinct elements left to generate.
	size_t size() const { return idx_.size(); }

	// Generates a random element from container uniformly.
	// O(log n).
	T gen() { return list_[idx_.gen()]; }

	// Generates a list of distinct values.
	// O(size * log(n)).
	auto gen_list(int size) {
		std::vector<T> res;
		for (int i = 0; i < size; ++i)
			res.push_back(gen());
		return typename list<T>::value(res);
	}

	// Generates all distinct values.
	// O(n log(n))
	auto gen_all() {
		std::vector<T> res;
		while (size() > 0)
			res.push_back(gen());
		return typename list<T>::value(res);
	}
};
template <typename C>
distinct_container(const C &) -> distinct_container<typename C::value_type>;

/************
 *          *
 *   OPTS   *
 *          *
 ************/

/*
 * Opts - options given to the generator.
 *
 * Incompatible with testlib.
 *
 * Opts are a list of either positional or named options.
 *
 * Named options is given in one of the following formats:
 * 1) -keyname=value or --keyname=value (ex. -n=10   , --test-count=20)
 * 2) -keyname value or --keyname value (ex. -n 10   , --test-count 20)
 *
 * Positional options are number from 0 sequentially.
 * For example, for "10 -n=20 str" positional option 1 is the string "str".
 */

/*
 * C++ version selection.
 */

// Sets C++ version.
inline void set_cpp_version(int version) {
	detail::cpp = detail::cpp_value(version);
}

/*
 * Compiler selection.
 */

// GCC compiler type.
inline detail::compiler_value gcc(int major = 0, int minor = 0) {
	return {detail::compiler_kind::gcc, major, minor};
}

// Clang compiler type.
inline detail::compiler_value clang(int major = 0, int minor = 0) {
	return {detail::compiler_kind::clang, major, minor};
}

// Sets compiler.
inline void set_compiler(detail::compiler_value compiler) {
	detail::compiler.kind_ = compiler.kind_;
	detail::compiler.major_ = compiler.major_;
	detail::compiler.minor_ = compiler.minor_;
}

namespace detail {

// Processes special opt flags.
// Returns true if the key is a special opt flag.
inline bool process_special_opt_flags(std::string &key) {
	// Checks for gen::CPP=17|20|23
	if (key.find("tgen::CPP:") == 0) {
		int prefix_len = std::string("tgen::CPP:").size();
		tgen_ensure(static_cast<int>(key.size()) == prefix_len + 2 and
						std::isdigit(key[prefix_len]) and
						std::isdigit(key[prefix_len + 1]),
					"invalid CPP format");
		int version = std::stoi(key.substr(prefix_len, 2));
		set_cpp_version(version);
		return true;
	}

	// Checks for tgen::(GCC|CLANG) or
	// tgen::(GCC|CLANG):(version|version.minor).
	compiler_kind kind;
	size_t prefix_len = 0;

	if (key.find("tgen::GCC") == 0) {
		kind = compiler_kind::gcc;
		prefix_len = std::string("tgen::GCC").size();
	} else if (key.find("tgen::CLANG") == 0) {
		kind = compiler_kind::clang;
		prefix_len = std::string("tgen::CLANG").size();
	} else {
		return false;
	}

	if (key.size() == prefix_len) {
		set_compiler(compiler_value(kind, 0, 0));
		return true;
	}

	tgen_ensure(key[prefix_len] == ':', "invalid compiler format");
	++prefix_len; // for ':'.

	std::string inside = key.substr(prefix_len, key.size() - prefix_len);
	int major = 0, minor = 0;

	size_t dot = inside.find('.');
	if (dot == std::string::npos) {
		tgen_ensure(!inside.empty() and
						std::all_of(inside.begin(), inside.end(), ::isdigit),
					"invalid compiler version");
		major = std::stoi(inside);
	} else {
		std::string maj = inside.substr(0, dot);
		std::string min = inside.substr(dot + 1);

		tgen_ensure(!maj.empty() and
						std::all_of(maj.begin(), maj.end(), ::isdigit) and
						maj.size() <= 3,
					"invalid compiler major version");
		tgen_ensure(!min.empty() and
						std::all_of(min.begin(), min.end(), ::isdigit) and
						min.size() <= 3,
					"invalid compiler minor version");

		major = std::stoi(maj);
		minor = std::stoi(min);
	}

	set_compiler(compiler_value(kind, major, minor));

	return true;
}

inline std::vector<std::string>
	pos_opts; // Dictionary containing the positional parsed opts.
inline std::map<std::string, std::string>
	named_opts; // Global dictionary the named parsed opts.

template <typename T> T get_opt(const std::string &value) {
	try {
		if constexpr (std::is_same_v<T, bool>) {
			if (value == "true" or value == "1")
				return true;
			if (value == "false" or value == "0")
				return false;
		} else if constexpr (std::is_integral_v<T>) {
			if constexpr (std::is_unsigned_v<T>)
				return static_cast<T>(std::stoull(value));
			else
				return static_cast<T>(std::stoll(value));
		} else if constexpr (std::is_floating_point_v<T>)
			return static_cast<T>(std::stold(value));
		else
			return value; // default: std::string
	} catch (...) {
	}

	throw error("invalid value `" + value + "` for type " + typeid(T).name());
}

inline void parse_opts(int argc, char **argv) {
	// Parses the opts into `pos_opts` vector and `named_opts`
	// map. Starting from 1 to ignore the name of the executable.
	for (int i = 1; i < argc; ++i) {
		std::string key(argv[i]);

		if (process_special_opt_flags(key))
			continue;

		if (key[0] == '-') {
			tgen_ensure(key.size() > 1,
						"invalid opt (" + std::string(argv[i]) + ")");
			if ('0' <= key[1] and key[1] <= '9') {
				// This case is a positional negative number argument
				pos_opts.push_back(key);
				continue;
			}

			// pops first char '-'
			key = key.substr(1);
		} else {
			// This case is a positional argument that does not start with '-'
			pos_opts.push_back(key);
			continue;
		}

		// Pops a possible second char '-'.
		if (key[0] == '-') {
			tgen_ensure(key.size() > 1,
						"invalid opt (" + std::string(argv[i]) + ")");

			// pops first char '-'
			key = key.substr(1);
		}

		// Assumes that, if it starts with '-' and second char is not a digit,
		// then it is a <key, value> pair.
		// 1 or 2 chars '-' have already been poped.

		std::size_t eq = key.find('=');
		if (eq != std::string::npos) {
			// This is the '--key=value' case.
			std::string value = key.substr(eq + 1);
			key = key.substr(0, eq);
			tgen_ensure(!key.empty() and !value.empty(),
						"expected non-empty key/value in opt (" +
							std::string(argv[1]));
			tgen_ensure(named_opts.count(key) == 0,
						"cannot have repeated keys");
			named_opts[key] = value;
		} else {
			// This is the '--key value' case.
			tgen_ensure(named_opts.count(key) == 0,
						"cannot have repeated keys");
			tgen_ensure(argv[i + 1], "value cannot be empty");
			named_opts[key] = std::string(argv[i + 1]);
			++i;
		}
	}
}

inline void set_seed(int argc, char **argv) {
	std::vector<uint32_t> seed;

	// Starting from 1 to ignore the name of the executable.
	for (int i = 1; i < argc; ++i) {
		// We append the number of chars, and then the list of chars.
		int size_pos = seed.size();
		seed.push_back(0);
		for (char *s = argv[i]; *s != '\0'; ++s) {
			++seed[size_pos];
			seed.push_back(*s);
		}
	}
	std::seed_seq seq(seed.begin(), seed.end());
	rng.seed(seq);
}

} // namespace detail

// Returns true if there is an opt at a given index.
inline bool has_opt(std::size_t index) {
	detail::ensure_registered();
	return 0 <= index and index < detail::pos_opts.size();
}

// Returns true if there is an opt with a given key.
inline bool has_opt(const std::string &key) {
	detail::ensure_registered();
	return detail::named_opts.count(key) != 0;
}
template <typename K>
std::enable_if_t<std::is_same_v<K, char>, bool> has_opt(K key) {
	return has_opt(std::string(1, key));
}

// Returns the parsed opt by a given index. If no opts with the given index are
// found, returns the given default_value.
template <typename T>
T opt(size_t index, std::optional<T> default_value = std::nullopt) {
	detail::ensure_registered();
	if (!has_opt(index)) {
		if (default_value)
			return *default_value;
		throw detail::error("cannot find key with index " +
							std::to_string(index));
	}
	return detail::get_opt<T>(detail::pos_opts[index]);
}

// Returns the parsed opt by a given key. If no opts with the given key are
// found, returns the given default_value.
template <typename T>
T opt(const std::string &key, std::optional<T> default_value = std::nullopt) {
	detail::ensure_registered();
	if (!has_opt(key)) {
		if (default_value)
			return *default_value;
		throw detail::error("cannot find key with key " + key);
	}
	return detail::get_opt<T>(detail::named_opts[key]);
}
template <typename T, typename K>
std::enable_if_t<std::is_same_v<K, char>, T>
opt(K key, std::optional<T> default_value = std::nullopt) {
	return opt<T>(std::string(1, key), default_value);
}

// Registers generator by initializing rnd and parsing opts.
inline void register_gen(int argc, char **argv) {
	detail::set_seed(argc, argv);

	detail::pos_opts.clear();
	detail::named_opts.clear();
	detail::parse_opts(argc, argv);

	detail::registered = true;
}

// Registers generator by initializing rnd with a given seed.
inline void register_gen(std::optional<long long> seed = std::nullopt) {
	if (seed)
		detail::rng.seed(*seed);
	else
		detail::rng.seed();

	detail::pos_opts.clear();
	detail::named_opts.clear();

	detail::registered = true;
}

/************
 *          *
 *   LIST   *
 *          *
 ************/

/*
 * List generator.
 *
 * List of integral types.
 */

template <typename T> struct list : gen_base<list<T>> {
	int size_;			  // Size of list.
	T value_l_, value_r_; // Range of defined values.
	std::set<T> values_;  // Set of values. If empty, use range. if not,
						  // represents the possible values, and the range
						  // represents the index in this set)
	std::map<T, int>
		value_idx_in_set_; // Index of every value in the set above.
	std::vector<std::pair<T, T>> val_range_; // Range of values of each index.
	std::vector<std::vector<int>> neigh_;	 // Adjacency list of equality.
	std::vector<std::set<int>>
		diff_restrictions_; // All different restrictions.

	// Creates generator for lists of size 'size', with random T in [value_left,
	// value_right].
	list(int size, T value_left, T value_right)
		: size_(size), value_l_(value_left), value_r_(value_right),
		  neigh_(size) {
		tgen_ensure(size_ > 0, "list: size must be positive");
		tgen_ensure(value_l_ <= value_r_, "list: value range must be valid");
		for (int i = 0; i < size_; ++i)
			val_range_.emplace_back(value_l_, value_r_);
	}

	// Creates list with value set.
	list(int size, std::set<T> values)
		: size_(size), values_(values), neigh_(size) {
		tgen_ensure(size_ > 0, "list: size must be positive");
		tgen_ensure(!values.empty(), "list: value set must be non-empty");
		value_l_ = 0, value_r_ = values.size() - 1;
		for (int i = 0; i < size_; ++i)
			val_range_.emplace_back(value_l_, value_r_);
		int idx = 0;
		for (T val : values_)
			value_idx_in_set_[val] = idx++;
	}

	// Restricts lists for list[idx] = val.
	list &fix(int idx, T val) {
		tgen_ensure(0 <= idx and idx < size_, "list: index must be valid");
		if (values_.size() == 0) {
			auto &[left, right] = val_range_[idx];
			if (left == right and value_l_ != value_r_) {
				tgen_ensure(left == val,
							"list: must not set to two different values");
			} else {
				tgen_ensure(left <= val and val <= right,
							"list: value must be in the defined range");
			}
			left = right = val;
		} else {
			tgen_ensure(values_.count(val),
						"list: value must be in the set of values");
			auto &[left, right] = val_range_[idx];
			int new_val = value_idx_in_set_[val];
			tgen_ensure(left <= new_val and new_val <= right,
						"list: must not set to two different values");
			left = right = new_val;
		}
		return *this;
	}

	// Restricts lists for list[idx_1] = list[idx_2].
	list &equal(int idx_1, int idx_2) {
		tgen_ensure(0 <= std::min(idx_1, idx_2) and
						std::max(idx_1, idx_2) < size_,
					"list: indices must be valid");
		if (idx_1 == idx_2)
			return *this;

		neigh_[idx_1].push_back(idx_2);
		neigh_[idx_2].push_back(idx_1);
		return *this;
	}

	// Restricts lists for list[S] to be equal, for given subset S of indices.
	list &equal(std::set<int> indices) {
		if (!indices.empty()) {
			std::set<int>::iterator beg = indices.begin();
			for (auto it = std::next(beg); it != indices.end(); ++it)
				equal(*beg, *it);
		}
		return *this;
	}

	// Restricts lists for list[left..right] to have all equal values.
	list &equal_range(int left, int right) {
		tgen_ensure(0 <= left and left <= right and right < size_,
					"list: range indices must be valid");
		for (int i = left; i < right; ++i)
			equal(i, i + 1);
		return *this;
	}

	// Restricts lists for all equal elements.
	list &all_equal() { return equal_range(0, size_ - 1); }

	// Restricts lists for list[S] to be different (distinct), for given subset
	// S of indices. You can not add two of these restrictions with
	// intersection.
	list &different(std::set<int> indices) {
		if (!indices.empty())
			diff_restrictions_.push_back(indices);
		return *this;
	}

	// Restricts lists for list[idx_1] != list[idx_2].
	list &different(int idx_1, int idx_2) {
		std::set<int> indices = {idx_1, idx_2};
		return different(indices);
	}

	// Restricts lists for list[left..right] to have all different values.
	list &different_range(int left, int right) {
		tgen_ensure(0 <= left and left <= right and right < size_,
					"list: range indices must be valid");
		std::vector<int> indices(right - left + 1);
		std::iota(indices.begin(), indices.end(), left);
		return different(std::set<int>(indices.begin(), indices.end()));
	}

	// Restricts lists for all different elements.
	list &all_different() {
		std::vector<int> indices(size_);
		std::iota(indices.begin(), indices.end(), 0);
		return different(std::set<int>(indices.begin(), indices.end()));
	}

	// List value.
	// Operations on a value are not random.
	struct value : gen_value_base<value> {
		using tgen_is_sequential_tag = detail::is_sequential_tag;
		using tgen_has_subset_defined_tag = detail::has_subset_defined_tag;

		using value_type = T;			 // Value type, for templates.
		using std_type = std::vector<T>; // std type for value.
		std::vector<T> vec_;			 // list.
		char sep_;						 // Separator for printing.

		value(const std::vector<T> &vec) : vec_(vec), sep_(' ') {}
		value(const std::initializer_list<T> &il) : value(std::vector<T>(il)) {}

		// Fetches size.
		int size() const { return vec_.size(); }

		// Fetches position idx.
		T &operator[](int idx) {
			tgen_ensure(0 <= idx and idx < size(),
						"list: value: index out of bounds");
			return vec_[idx];
		}
		const T &operator[](int idx) const {
			tgen_ensure(0 <= idx and idx < size(),
						"list: value: index out of bounds");
			return vec_[idx];
		}

		// Sorts values in non-decreasing order.
		// O(n log n).
		value &sort() {
			std::sort(vec_.begin(), vec_.end());
			return *this;
		}

		// Reverses list.
		// O(n).
		value &reverse() {
			std::reverse(vec_.begin(), vec_.end());
			return *this;
		}

		// Sets the separator for the list, for printing.
		// O(1).
		value &separator(char sep) {
			sep_ = sep;
			return *this;
		}

		// Concatenates two values.
		// Linear.
		value operator+(const value &rhs) const {
			std::vector<T> new_vec = vec_;
			for (int i = 0; i < rhs.size(); ++i)
				new_vec.push_back(rhs[i]);
			return value(new_vec);
		}

		// Prints to std::ostream, separated by sep_.
		friend std::ostream &operator<<(std::ostream &out, const value &val) {
			for (int i = 0; i < val.size(); ++i) {
				if (i > 0)
					out << val.sep_;
				out << val[i];
			}
			return out;
		}

		// Gets a std::vector representing the value.
		auto to_std() const {
			if constexpr (!is_generator_value<T>::value) {
				return vec_;
			} else {
				std::vector<typename T::std_type> vec;
				for (const auto &i : vec_)
					vec.push_back(i.to_std());
				return vec;
			}
		}
	};

	// Generates a uniformly random list of k distinct values in `[value_l,
	// value_r]`, such that no value is in `forbidden_values`.
	std::vector<T>
	generate_distinct_values(int k, const std::set<T> &forbidden_values) const {
		for (auto forbidden : forbidden_values)
			tgen_ensure(value_l_ <= forbidden and forbidden <= value_r_);
		// We generate our numbers in the range [0, num_available) with
		// num_available = (r-l+1)-(forbidden_values.size()), and then map them
		// to the correct range. We will run k steps of Fisher–Yates, using a
		// map to store a virtual list that starts with a[i] = i.
		T num_available = (value_r_ - value_l_ + 1) - forbidden_values.size();
		if (num_available < k)
			throw detail::complex_restrictions_error(
				"list", "not enough distinct values");
		std::map<T, T> virtual_list;
		std::vector<T> gen_list;
		for (int i = 0; i < k; ++i) {
			T j = next<T>(i, num_available - 1);
			T vj = virtual_list.count(j) ? virtual_list[j] : j;
			T vi = virtual_list.count(i) ? virtual_list[i] : i;

			virtual_list[j] = vi, virtual_list[i] = vj;

			gen_list.push_back(virtual_list[i]);
		}

		// Shifts back to correct range, but there might still be values
		// that we can not use.
		for (T &val : gen_list)
			val += value_l_;

		// Now for every generated value, we shift it by how many forbidden
		// values are <= to it.
		std::vector<std::pair<T, int>> values_sorted;
		for (std::size_t i = 0; i < gen_list.size(); ++i)
			values_sorted.emplace_back(gen_list[i], i);
		// We iterate through them in increasing order.
		std::sort(values_sorted.begin(), values_sorted.end());
		auto cur_it = forbidden_values.begin();
		int smaller_forbidden_count = 0;
		for (auto [val, idx] : values_sorted) {
			while (cur_it != forbidden_values.end() and
				   *cur_it <= val + smaller_forbidden_count)
				++cur_it, ++smaller_forbidden_count;
			gen_list[idx] += smaller_forbidden_count;
		}

		return gen_list;
	}

	// Generates list value.
	// O(n log n).
	value gen() const {
		std::vector<T> vec(size_);
		std::vector<bool> defined_idx(
			size_, false); // For every index, if it has been set in `vec`.

		std::vector<int> comp_id(size_, -1); // Component id of each index.
		std::vector<std::vector<int>> comp(size_); // Component of each comp-id.
		int comp_count = 0; // Number of different components.

		// Defines value of entire component.
		auto define_comp = [&](int cur_comp, T val) {
			for (int idx : comp[cur_comp]) {
				tgen_ensure(!defined_idx[idx]);
				vec[idx] = val;
				defined_idx[idx] = true;
			}
		};

		// Groups = components.
		{
			std::vector<bool> vis(size_, false); // Visited for each index.
			for (int idx = 0; idx < size_; ++idx)
				if (!vis[idx]) {
					T new_value;
					bool value_defined = false;

					// BFS to visit the connected component, grouping equal
					// values.
					std::queue<int> q({idx});
					vis[idx] = true;
					std::vector<int> component;
					while (!q.empty()) {
						int cur_idx = q.front();
						q.pop();

						component.push_back(cur_idx);

						// Checks value.
						auto [l, r] = val_range_[cur_idx];
						if (l == r) {
							if (!value_defined) {
								// We found the value.
								value_defined = true;
								new_value = l;
							} else if (new_value != l) {
								// We found a contradiction
								throw detail::contradiction_error(
									"list",
									"tried to set value to `" +
										std::to_string(new_value) +
										"`, but it was already set as `" +
										std::to_string(l) + "`");
							}
						}

						for (int nxt_idx : neigh_[cur_idx]) {
							if (!vis[nxt_idx]) {
								vis[nxt_idx] = true;
								q.push(nxt_idx);
							}
						}
					}

					// Group entire component, checking if value is defined.
					for (int cur_idx : component) {
						comp_id[cur_idx] = comp_count;
						comp[comp_id[cur_idx]].push_back(cur_idx);
					}

					// Defines value if needed.
					if (value_defined)
						define_comp(comp_count, new_value);

					++comp_count;
				}
		}

		// Initial parsing of different restrictions.
		std::vector<std::set<int>> diff_containing_comp_idx(comp_count);
		{
			int dist_id = 0;
			for (const std::set<int> &diff : diff_restrictions_) {
				// Checks if there are too many different values.
				if (static_cast<uint64_t>(diff.size() - 1) +
						static_cast<uint64_t>(value_l_) >
					static_cast<uint64_t>(value_r_))
					throw detail::contradiction_error(
						"list", "tried to generate " +
									std::to_string(diff.size()) +
									" different values, but the maximum is " +
									std::to_string(value_r_ - value_l_ + 1));

				// Checks if two values in same component are marked as
				// different.
				std::set<int> comp_ids;
				for (int idx : diff) {
					if (comp_ids.count(comp_id[idx]))
						throw detail::contradiction_error(
							"list", "tried to set two indices as equal and "
									"different");
					comp_ids.insert(comp_id[idx]);

					diff_containing_comp_idx[comp_id[idx]].insert(dist_id);
				}
				++dist_id;
			}
		}

		// If some value is in >= 3 sets, then there is a cycle.
		for (auto &diff_containing : diff_containing_comp_idx)
			if (diff_containing.size() >= 3)
				throw detail::complex_restrictions_error(
					"list",
					"one index can not be in >= 3 'different' restrictions");

		std::vector<bool> vis_diff(diff_restrictions_.size(), false);
		std::vector<bool> initially_defined_comp_idx(comp_count, false);

		// Fills the value in a tree defined by "different" restrictions.
		auto define_tree = [&](int diff_id) {
			// The set `diff_restrictions_[diff_id]` can have some
			// values that are defined.

			// Generates set of already defined values.
			std::set<T> defined_values;
			for (int idx : diff_restrictions_[diff_id])
				if (defined_idx[idx]) {
					// Checks if two values in `diff_restrictions_[dist_id]`
					// have been set to the same value
					if (defined_values.count(vec[idx]))
						throw detail::contradiction_error(
							"list",
							"tried to set two indices as equal and different");

					defined_values.insert(vec[idx]);
				}

			// Generates values in this root "different" restriction.
			{
				int new_value_count = diff_restrictions_[diff_id].size() -
									  static_cast<int>(defined_values.size());
				std::vector<T> generated_values =
					generate_distinct_values(new_value_count, defined_values);
				auto val_it = generated_values.begin();
				for (int idx : diff_restrictions_[diff_id])
					if (defined_idx[idx]) {
						// The root can cover these components, but there should
						// not be any other defined in this tree.
						initially_defined_comp_idx[comp_id[idx]] = false;
					} else {
						define_comp(comp_id[idx], *val_it);
						++val_it;
					}
			}

			// BFS on the tree of "different" restrictions.
			std::queue<std::pair<int, int>> q; // {id, parent id}
			q.emplace(diff_id, -1);
			vis_diff[diff_id] = true;
			while (!q.empty()) {
				auto [cur_diff, parent] = q.front();
				q.pop();

				std::set<int> neigh_diff;
				for (int idx : diff_restrictions_[cur_diff])
					for (int nxt_diff :
						 diff_containing_comp_idx[comp_id[idx]]) {
						if (nxt_diff == cur_diff or nxt_diff == parent)
							continue;

						// Cycle found.
						if (vis_diff[nxt_diff])
							throw detail::complex_restrictions_error(
								"list",
								"cycle found in 'different' restrictions");

						neigh_diff.insert(nxt_diff);
					}

				for (int nxt_diff : neigh_diff) {
					vis_diff[nxt_diff] = true;
					q.emplace(nxt_diff, cur_diff);

					// Generates this "different" restriction.
					std::set<T> nxt_defined_values;
					for (int idx2 : diff_restrictions_[nxt_diff])
						if (defined_idx[idx2]) {
							// There can not be any more defined. This case is
							// when there are values not coverered by a single
							// "different" restriction in the tree.
							if (initially_defined_comp_idx[comp_id[idx2]])
								throw detail::complex_restrictions_error(
									"list");

							nxt_defined_values.insert(vec[idx2]);
						}
					int new_value_count =
						diff_restrictions_[nxt_diff].size() -
						static_cast<int>(nxt_defined_values.size());
					std::vector<T> generated_values = generate_distinct_values(
						new_value_count, nxt_defined_values);
					auto val_it = generated_values.begin();
					for (int idx2 : diff_restrictions_[nxt_diff])
						if (!defined_idx[idx2]) {
							define_comp(comp_id[idx2], *val_it);
							++val_it;
						}
				}
			}
		};

		// Loops through "different" restrictions, sorts "different"
		// restrictions by number of defined components (non-increasing). This
		// guarantees that if there is a valid root (that covers all 'defined'),
		// we find it.
		{
			std::vector<std::pair<int, int>> defined_cnt_and_diff_idx;
			int dist_id = 0;
			for (const std::set<int> &diff : diff_restrictions_) {
				int defined_cnt = 0;
				for (int idx : diff)
					if (defined_idx[idx]) {
						++defined_cnt;
						initially_defined_comp_idx[comp_id[idx]] = true;
					}
				defined_cnt_and_diff_idx.emplace_back(defined_cnt, dist_id);
				++dist_id;
			}

			std::sort(defined_cnt_and_diff_idx.rbegin(),
					  defined_cnt_and_diff_idx.rend());
			for (auto [defined_cnt, diff_idx] : defined_cnt_and_diff_idx)
				if (!vis_diff[diff_idx])
					define_tree(diff_idx);
		}

		// Loops through "different" restrictions do define the rest.
		for (std::size_t dist_id = 0; dist_id < diff_restrictions_.size();
			 ++dist_id)
			if (!vis_diff[dist_id])
				define_tree(dist_id);

		// Define final values. These values all should be random in [l, r], and
		// the "different" restrictions have already been processed. However,
		// there can be still equality restrictions, so we define entire
		// components.
		for (int idx = 0; idx < size_; ++idx)
			if (!defined_idx[idx])
				define_comp(comp_id[idx], next<T>(value_l_, value_r_));

		if (!values_.empty()) {
			// Needs to fetch the values from the value set.
			std::vector<T> value_vec(values_.begin(), values_.end());
			for (T &val : vec)
				val = value_vec[val];
		}

		return value(vec);
	}
};

/*******************
 *                 *
 *   PERMUTATION   *
 *                 *
 *******************/

/*
 * Permutation generation.
 *
 * Permutation are defined always as numbers in [0, n), that is, 0-based.
 */

struct permutation : gen_base<permutation> {
	int size_;									  // Size of permutation.
	std::vector<std::pair<int, int>> defs_;		  // {idx, value}.
	std::optional<std::vector<int>> cycle_sizes_; // Cycle sizes.

	// Creates generator for permutation of size 'size'.
	permutation(int size) : size_(size) {
		tgen_ensure(size_ > 0, "permutation: size must be positive");
	}

	// Restricts permutations for permutation[idx] = val.
	permutation &fix(int idx, int val) {
		tgen_ensure(0 <= idx and idx < size_,
					"permutation: index must be valid");
		defs_.emplace_back(idx, val);
		return *this;
	}

	// Restricts permutations for permutation to have cycle sizes.
	permutation &cycles(const std::vector<int> &cycle_sizes) {
		tgen_ensure(
			size_ == std::accumulate(cycle_sizes.begin(), cycle_sizes.end(), 0),
			"permutation: cycle sizes must add up to size of permutation");
		cycle_sizes_ = cycle_sizes;
		return *this;
	}
	permutation &cycles(const std::initializer_list<int> &cycle_sizes) {
		return cycles(std::vector<int>(cycle_sizes));
	}

	// Permutation value.
	// Operations on a value are not random.
	struct value : gen_value_base<value> {
		using tgen_is_sequential_tag = detail::is_sequential_tag;

		using std_type = std::vector<int>; // std type for value.
		std::vector<int> vec_;			   // Permutation.
		char sep_;						   // Separator for printing.
		bool add_1_;					   // If should add 1, for printing.

		value(const std::vector<int> &vec)
			: vec_(vec), sep_(' '), add_1_(false) {
			tgen_ensure(!vec_.empty(), "permutation: value: cannot be empty");
			std::vector<bool> vis(vec_.size(), false);
			for (int i = 0; i < size(); ++i) {
				tgen_ensure(0 <= vec_[i] and
								vec_[i] < static_cast<int>(vec_.size()),
							"permutation: value: values must be from `0` to "
							"`size-1`");
				tgen_ensure(!vis[vec_[i]],
							"permutation: value: cannot have repeated values");
				vis[vec_[i]] = true;
			}
		}
		value(const std::initializer_list<int> &il)
			: value(std::vector<int>(il)) {}

		// Fetches size.
		int size() const { return vec_.size(); }

		// Fetches position idx.
		const int &operator[](int idx) const {
			tgen_ensure(0 <= idx and idx < size(),
						"permutation: value: index out of bounds");
			return vec_[idx];
		}

		// Returns parity of the permutation (+1 if even, -1 if odd).
		// O(n).
		int parity() const {
			std::vector<bool> vis(size(), false);
			int cycles = 0;

			for (int i = 0; i < size(); ++i)
				if (!vis[i]) {
					++cycles;
					for (int j = i; !vis[j]; j = vec_[j])
						vis[j] = true;
				}
			// Even iff (n - cycles) is even.
			return ((size() - cycles) % 2 == 0) ? +1 : -1;
		}

		// Sorts values in increasign order.
		// O(n).
		value &sort() {
			for (int i = 0; i < size(); ++i)
				vec_[i] = i;
			return *this;
		}

		// Reverses permutation.
		// O(n).
		value &reverse() {
			std::reverse(vec_.begin(), vec_.end());
			return *this;
		}

		// Inverse of the permutation.
		// O(n).
		value &inverse() {
			std::vector<int> inv(size());
			for (int i = 0; i < size(); ++i)
				inv[vec_[i]] = i;
			swap(vec_, inv);
			return *this;
		}

		// Sets the separator, for printing.
		// O(1).
		value &separator(char sep) {
			sep_ = sep;
			return *this;
		}

		// Sets that should print values 1-based.
		// O(1).
		value &add_1() {
			add_1_ = true;
			return *this;
		}

		// Prints to std::ostream, separated by sep_.
		friend std::ostream &operator<<(std::ostream &out, const value &val) {
			for (int i = 0; i < val.size(); ++i) {
				if (i > 0)
					out << val.sep_;
				out << val[i] + val.add_1_;
			}
			return out;
		}

		// Gets a std::vector representing the value.
		std::vector<int> to_std() const { return vec_; }
	};

	// Generates permutation value.
	// O(n).
	value gen() const {
		if (!cycle_sizes_) {
			// Cycle sizes not specified.
			std::vector<int> idx_to_val(size_, -1), val_to_idx(size_, -1);
			for (auto [idx, val] : defs_) {
				tgen_ensure(
					0 <= val and val < size_,
					"permutation: value in permutation must be in [0, " +
						std::to_string(size_) + ")");

				if (idx_to_val[idx] != -1) {
					tgen_ensure(idx_to_val[idx] == val,
								"permutation: cannot set an idex to two "
								"different values");
				} else
					idx_to_val[idx] = val;

				if (val_to_idx[val] != -1) {
					tgen_ensure(val_to_idx[val] == idx,
								"permutation: cannot set two indices to the "
								"same value");
				} else
					val_to_idx[val] = idx;
			}

			std::vector<int> perm(size_);
			std::iota(perm.begin(), perm.end(), 0);
			shuffle(perm.begin(), perm.end());
			int cur_idx = 0;
			for (int &i : idx_to_val)
				if (i == -1) {
					// While this value is used, skip.
					while (val_to_idx[perm[cur_idx]] != -1)
						++cur_idx;
					i = perm[cur_idx++];
				}
			return idx_to_val;
		}

		// Creates cycles.
		std::vector<int> order(size_);
		std::iota(order.begin(), order.end(), 0);
		shuffle(order.begin(), order.end());
		int idx = 0;
		std::vector<std::vector<int>> cycles;
		for (int cycle_size : *cycle_sizes_) {
			cycles.emplace_back();
			for (int i = 0; i < cycle_size; ++i)
				cycles.back().push_back(order[idx++]);
		}

		// Retrieves permutation from cycles.
		std::vector<int> perm(size_, -1);
		for (const std::vector<int> &cycle : cycles) {
			int cur_size = cycle.size();
			for (int i = 0; i < cur_size; ++i)
				perm[cycle[i]] = cycle[(i + 1) % cur_size];
		}

		return value(perm);
	}
};

/************
 *          *
 *   MATH   *
 *          *
 ************/

namespace math {

namespace detail {

using namespace tgen::detail;

inline int popcount(uint64_t x) { return __builtin_popcountll(x); }

inline int ctzll(uint64_t x) {
	// Mistery code found on the internet.
	// Uses de Brujin sequence.
	static const unsigned char index64[64] = {
		0,	1,	2,	53, 3,	7,	54, 27, 4,	38, 41, 8,	34, 55, 48, 28,
		62, 5,	39, 46, 44, 42, 22, 9,	24, 35, 59, 56, 49, 18, 29, 11,
		63, 52, 6,	26, 37, 40, 33, 47, 61, 45, 43, 21, 23, 58, 17, 10,
		51, 25, 36, 32, 60, 20, 57, 16, 50, 31, 19, 15, 30, 14, 13, 12};
	return index64[((x & -x) * 0x022FDD63CC95386D) >> 58];
}

inline uint64_t mul_mod(uint64_t a, uint64_t b, uint64_t m) {
	return static_cast<u128>(a) * b % m;
}

// O(log n).
// 0 <= x < m.
inline uint64_t expo_mod(uint64_t x, uint64_t y, uint64_t m) {
	if (!y)
		return 1;
	uint64_t ans = expo_mod(mul_mod(x, x, m), y / 2, m);
	return y % 2 ? mul_mod(x, ans, m) : ans;
}

} // namespace detail

// O(log^2 n).
inline bool is_prime(uint64_t n) {
	if (n < 2)
		return false;
	if (n == 2 or n == 3)
		return true;
	if (n % 2 == 0)
		return false;

	uint64_t r = detail::ctzll(n - 1), d = n >> r;
	// These bases are guaranteed to work for n <= 2^64.
	for (int a : {2, 325, 9375, 28178, 450775, 9780504, 1795265022}) {
		uint64_t x = detail::expo_mod(a, d, n);
		if (x == 1 or x == n - 1 or a % n == 0)
			continue;

		for (uint64_t j = 0; j < r - 1; ++j) {
			x = detail::mul_mod(x, x, n);
			if (x == n - 1)
				break;
		}
		if (x != n - 1)
			return false;
	}
	return true;
}

namespace detail {

inline uint64_t pollard_rho(uint64_t n) {
	if (n == 1 or is_prime(n))
		return n;
	auto f = [n](uint64_t x) { return mul_mod(x, x, n) + 1; };

	uint64_t x = 0, y = 0, t = 30, prd = 2, x0 = 1, q;
	while (t % 40 != 0 or std::gcd(prd, n) == 1) {
		if (x == y)
			x = ++x0, y = f(x);
		q = mul_mod(prd, x > y ? x - y : y - x, n);
		if (q != 0)
			prd = q;
		x = f(x), y = f(f(y)), ++t;
	}
	return std::gcd(prd, n);
}

inline std::vector<uint64_t> factor(uint64_t n) {
	if (n == 1)
		return {};
	if (is_prime(n))
		return {n};
	uint64_t d = pollard_rho(n);
	std::vector<uint64_t> l = factor(d), r = factor(n / d);
	l.insert(l.end(), r.begin(), r.end());
	return l;
}

// Error handling.
template <typename T>
std::runtime_error there_is_no_in_range_error(const std::string &type, T l,
											  T r) {
	return error("math: there is no " + type + " in range [" +
				 std::to_string(l) + ", " + std::to_string(r) + "]");
}
template <typename T>
std::runtime_error there_is_no_from_error(const std::string &type, T r) {
	return error("math: there is no " + type + " from " + std::to_string(r));
}
template <typename T>
std::runtime_error there_is_no_upto_error(const std::string &type, T r) {
	return error("math: there is no " + type + " up to " + std::to_string(r));
}

// O(log mod).
// 0 < a < mod.
// gcd(a, mod) = 1.
inline i128 modular_inverse_128(i128 a, i128 mod) {
	tgen_ensure(0 < a and a < mod,
				"math: remainder must be positive and smaller than the mod");

	i128 t = 0, new_t = 1;
	i128 r = mod, new_r = a;

	while (new_r != 0) {
		i128 q = r / new_r;

		auto tmp_t = t - q * new_t;
		t = new_t;
		new_t = tmp_t;

		auto tmp_r = r - q * new_r;
		r = new_r;
		new_r = tmp_r;
	}

	tgen_ensure(r == 1, "math: remainder and mod must be coprime");

	if (t < 0)
		t += mod;
	return t;
}

// checks if a * b <= limit, for positive numbers.
inline bool mul_leq(uint64_t a, uint64_t b, uint64_t limit) {
	if (a == 0)
		return true;
	return a <= limit / b;
}

// base^exp, or null if base^exp > limit.
inline std::optional<uint64_t> expo(uint64_t base, uint64_t exp,
									uint64_t limit) {
	uint64_t result = 1;

	while (exp) {
		if (exp & 1) {
			if (!mul_leq(result, base, limit))
				return std::nullopt;
			result *= base;
		}

		exp >>= 1;
		// Necesary for correctness.
		if (!exp)
			break;

		if (!mul_leq(base, base, limit))
			return std::nullopt;
		base *= base;
	}
	return result;
}

// O(log n log k).
// 0 < k.
inline uint64_t kth_root_floor(uint64_t n, uint64_t k) {
	tgen_ensure_against_bug(k > 0, "math: value must be valid");
	if (k == 1 or n <= 1)
		return n;

	uint64_t lo = 1, hi = 1ULL << ((64 + k - 1) / k);

	while (lo < hi) {
		uint64_t mid = lo + (hi - lo + 1) / 2;

		if (expo(mid, k, n)) {
			lo = mid;
		} else {
			hi = mid - 1;
		}
	}
	return lo;
}

// gcd(a, b).
// O(log a).
inline i128 gcd128(i128 a, i128 b) {
	if (a < 0)
		a = -a;
	if (b < 0)
		b = -b;
	while (b != 0) {
		i128 t = a % b;
		a = b;
		b = t;
	}
	return a;
}

// min(2^64, a*b).
// O(log a).
// a, b >= 0.
inline i128 mul_saturate(i128 a, i128 b) {
	tgen_ensure(a >= 0 and b >= 0);
	static const i128 LIMIT = static_cast<i128>(1) << 64;
	if (a == 0 or b == 0)
		return 0;
	if (a > LIMIT / b)
		return LIMIT;
	return a * b;
}

struct crt {
	using T = i128;
	T a, m;

	crt() : a(0), m(1) {}
	crt(T a_, T m_) : a(a_), m(m_) {}
	crt operator*(crt C) {
		if (m == 0 or C.m == 0)
			return {-1, 0};

		T g = gcd128(m, C.m);
		if ((C.a - a) % g != 0)
			return {-1, 0};

		T m1 = m / g;
		T m2 = C.m / g;

		if (m2 == 1)
			return {a, m};

		T inv = modular_inverse_128(m1 % m2, m2);

		T k = ((C.a - a) / g) % m2;
		if (k < 0)
			k += m2;

		k = static_cast<u128>(k) * inv % m2;

		T lcm = mul_saturate(m, m2);

		T res = (a + static_cast<T>((static_cast<u128>(k) * m) % lcm)) % lcm;
		if (res < 0)
			res += lcm;

		return {res, lcm};
	}
};

// Math hacks to operate on log space.

inline constexpr long double LOG_ZERO = -INFINITY;
inline constexpr long double LOG_ONE = 0.0;

inline long double log_space(long double x) {
	return x == 0.0 ? LOG_ZERO : std::log(x);
}

// Math hack to add two values in log space.
inline long double add_log_space(long double a, long double b) {
	if (a < b)
		std::swap(a, b);
	if (b == LOG_ZERO)
		return a;
	return a + log1p(exp(b - a));
}

// Math hack to subtract two values in log space.
// a >= b.
inline long double sub_log_space(long double a, long double b) {
	if (b >= a)
		return LOG_ZERO;
	if (b == LOG_ZERO)
		return a;
	return a + log1p(-exp(b - a));
}

} // namespace detail

// Sorted.
// O(n^(1/4) log n) expected.
// 0 < n.
inline std::vector<uint64_t> factor(uint64_t n) {
	tgen_ensure(n > 0, "math: number to factor must be positive");
	auto factors = detail::factor(n);
	std::sort(factors.begin(), factors.end());
	return factors;
}

// Sorted.
// O(n^(1/4) log n) expected.
// 0 < n.
inline std::vector<std::pair<uint64_t, int>> factor_by_prime(uint64_t n) {
	tgen_ensure(n > 0, "math: number to factor must be positive");
	std::vector<std::pair<uint64_t, int>> primes;
	for (uint64_t p : factor(n)) {
		if (!primes.empty() and primes.back().first == p)
			++primes.back().second;
		else
			primes.emplace_back(p, 1);
	}
	return primes;
}

// O(log mod).
// 0 < a < mod.
// gcd(a, mod) = 1.
inline uint64_t modular_inverse(uint64_t a, uint64_t mod) {
	return detail::modular_inverse_128(a, mod);
}

// O(n^(1/4) log n) expected.
// 0 < n.
inline uint64_t totient(uint64_t n) {
	tgen_ensure(n > 0, "math: totient(0) is undefined");
	uint64_t phi = n;

	for (auto [p, e] : factor_by_prime(n))
		phi -= phi / p;

	return phi;
}

// Returns `(p_i, g_i)`: `p_i` is the prime, `g_i` is the gap.
inline const std::pair<std::vector<uint64_t>, std::vector<uint64_t>> &
prime_gaps() {
	// From https://en.wikipedia.org/wiki/Prime_gap.
	static const std::pair<std::vector<uint64_t>, std::vector<uint64_t>> value{
		/* clang-format off */ {
			2, 3, 7, 23, 89, 113, 523, 887, 1129, 1327, 9551, 15683, 19609,
			31397, 155921, 360653, 370261, 492113, 1349533, 1357201, 2010733,
			4652353, 17051707, 20831323, 47326693, 122164747, 189695659,
			191912783, 387096133, 436273009, 1294268491, 1453168141,
			2300942549, 3842610773, 4302407359, 10726904659, 20678048297,
			22367084959, 25056082087, 42652618343, 127976334671, 182226896239,
			241160624143, 297501075799, 303371455241, 304599508537,
			416608695821, 461690510011, 614487453523, 738832927927,
			1346294310749, 1408695493609, 1968188556461, 2614941710599,
			7177162611713, 13829048559701, 19581334192423, 42842283925351,
			90874329411493, 171231342420521, 218209405436543, 1189459969825483,
			1686994940955803, 1693182318746371, 43841547845541059,
			55350776431903243, 80873624627234849, 203986478517455989,
			218034721194214273, 305405826521087869, 352521223451364323,
			401429925999153707, 418032645936712127, 804212830686677669,
			1425172824437699411, 5733241593241196731, 6787988999657777797
		}, /* clang-format on */
		{1,	   2,	 4,	   6,	 8,	   14,	 18,   20,	 22,   34,	 36,
		 44,   52,	 72,   86,	 96,   112,	 114,  118,	 132,  148,	 154,
		 180,  210,	 220,  222,	 234,  248,	 250,  282,	 288,  292,	 320,
		 336,  354,	 382,  384,	 394,  456,	 464,  468,	 474,  486,	 490,
		 500,  514,	 516,  532,	 534,  540,	 582,  588,	 602,  652,	 674,
		 716,  766,	 778,  804,	 806,  906,	 916,  924,	 1132, 1184, 1198,
		 1220, 1224, 1248, 1272, 1328, 1356, 1370, 1442, 1476, 1488, 1510}};

	return value;
}

// Returns pair (first_composite_in_gap, last_composite_in_gap).
// O(log(right)) approximately.
inline std::pair<uint64_t, uint64_t> prime_gap_upto(uint64_t right) {
	if (right < 4)
		throw detail::there_is_no_upto_error("prime gap", right);

	const auto &[P, G] = prime_gaps();
	for (int i = P.size() - 1;; --i) {
		if (P[i] >= right)
			continue;

		uint64_t real_right = std::min(right, P[i] + G[i] - 1);
		uint64_t prev = i > 0 ? G[i - 1] : 0;
		uint64_t curr = real_right - P[i];

		if (curr >= prev)
			return {P[i] + 1, real_right};
	}
}

// From https://oeis.org/A002182/b002182.txt.
inline const std::vector<uint64_t> &highly_composites() {
	/* clang-format off */
	static const std::vector<uint64_t> highly_composites = {
	1, 2, 4, 6, 12, 24, 36, 48, 60, 120, 180, 240, 360, 720, 840, 1260, 1680,
	2520, 5040, 7560, 10080, 15120, 20160, 25200, 27720, 45360, 50400, 55440,
	83160, 110880, 166320, 221760, 277200, 332640, 498960, 554400, 665280,
	720720, 1081080, 1441440, 2162160, 2882880, 3603600, 4324320, 6486480,
	7207200, 8648640, 10810800, 14414400, 17297280, 21621600, 32432400,
	36756720, 43243200, 61261200, 73513440, 110270160, 122522400, 147026880,
	183783600, 245044800, 294053760, 367567200, 551350800, 698377680, 735134400,
	1102701600, 1396755360, 2095133040, 2205403200, 2327925600, 2793510720,
	3491888400, 4655851200, 5587021440, 6983776800, 10475665200, 13967553600,
	20951330400, 27935107200, 41902660800, 48886437600, 64250746560,
	73329656400, 80313433200, 97772875200, 128501493120, 146659312800,
	160626866400, 240940299600, 293318625600, 321253732800, 481880599200,
	642507465600, 963761198400, 1124388064800, 1606268664000, 1686582097200,
	1927522396800, 2248776129600, 3212537328000, 3373164194400, 4497552259200,
	6746328388800, 8995104518400, 9316358251200, 13492656777600, 18632716502400,
	26985313555200, 27949074753600, 32607253879200, 46581791256000,
	48910880818800, 55898149507200, 65214507758400, 93163582512000,
	97821761637600, 130429015516800, 195643523275200, 260858031033600,
	288807105787200, 391287046550400, 577614211574400, 782574093100800,
	866421317361600, 1010824870255200, 1444035528936000, 1516237305382800,
	1732842634723200, 2021649740510400, 2888071057872000, 3032474610765600,
	4043299481020800, 6064949221531200, 8086598962041600, 10108248702552000,
	12129898443062400, 18194847664593600, 20216497405104000, 24259796886124800,
	30324746107656000, 36389695329187200, 48519593772249600, 60649492215312000,
	72779390658374400, 74801040398884800, 106858629141264000,
	112201560598327200, 149602080797769600, 224403121196654400,
	299204161595539200, 374005201994424000, 448806242393308800,
	673209363589963200, 748010403988848000, 897612484786617600,
	1122015605983272000, 1346418727179926400, 1795224969573235200,
	2244031211966544000, 2692837454359852800, 3066842656354276800,
	4381203794791824000, 4488062423933088000, 6133685312708553600,
	8976124847866176000, 9200527969062830400, 12267370625417107200ULL,
	15334213281771384000ULL, 18401055938125660800ULL}; /* clang-format on */
	return highly_composites;
}

// O(log(right)) approximately.
inline uint64_t highly_composite_upto(uint64_t right) {
	for (int i = highly_composites().size() - 1; i >= 0; --i)
		if (highly_composites()[i] <= right)
			return highly_composites()[i];

	throw detail::there_is_no_upto_error("highly composite number", right);
}

// O(log^3 (right)) expected.
// Generates a random prime in [left, right].
inline uint64_t gen_prime(uint64_t left, uint64_t right) {
	if (right < left or right < 2)
		throw detail::there_is_no_in_range_error("prime", left, right);
	left = std::max<uint64_t>(left, 2);
	auto [l_gap, r_gap] = prime_gap_upto(right);
	if (right - left + 1 <= r_gap - l_gap + 1) {
		// There might be no primes in the range.
		std::vector<uint64_t> vals(right - left + 1);
		iota(vals.begin(), vals.end(), left);
		shuffle(vals.begin(), vals.end());
		for (uint64_t i : vals)
			if (is_prime(i))
				return i;
		throw detail::there_is_no_in_range_error("prime", left, right);
	}

	uint64_t n;
	do {
		n = next(left, right);
	} while (!is_prime(n));
	return n;
}

// O(log^3 (left)) expected.
// left <= 2^64 - 59.
inline uint64_t prime_from(uint64_t left) {
	tgen_ensure(left <= std::numeric_limits<uint64_t>::max() - 58,
				"math: invalid bound");
	for (uint64_t i = std::max<uint64_t>(2, left);; ++i)
		if (is_prime(i))
			return i;
}

// O(log^3 (right)) expected.
inline uint64_t prime_upto(uint64_t right) {
	if (right >= 2)
		for (uint64_t i = right; i >= 2; --i)
			if (is_prime(i))
				return i;
	throw detail::there_is_no_upto_error("prime", right);
}

// O(n^(1/4) log n) expected.
// 0 < n.
inline int num_divisors(uint64_t n) {
	int divisors = 1;
	for (auto [p, e] : factor_by_prime(n))
		divisors *= (e + 1);
	return divisors;
}

// Random number in [left, right] with `divisor_count` divisors.
// O(log(right) log(divisor_count)).
// divisor_count must be prime.
inline uint64_t gen_divisor_count(uint64_t left, uint64_t right,
								  int divisor_count) {
	tgen_ensure(divisor_count > 0 and is_prime(divisor_count),
				"math: divisor count must be prime");
	int root = divisor_count - 1;
	uint64_t p = gen_prime(detail::kth_root_floor(left, root),
						   detail::kth_root_floor(right, root));
	return *detail::expo(p, root, right);
}

// O(|mods| + log (right)).
// |rems| = |mods|.
// rems_i < mods_i.
inline uint64_t gen_congruent(uint64_t left, uint64_t right,
							  std::vector<uint64_t> rems,
							  std::vector<uint64_t> mods) {
	if (left > right)
		throw detail::there_is_no_in_range_error("congruent number", left,
												 right);
	tgen_ensure(rems.size() == mods.size(),
				"math: number of remainders and mods must be the same");
	tgen_ensure(rems.size() > 0, "math: must have at least one congruence");

	detail::crt crt;
	for (int i = 0; i < static_cast<int>(rems.size()); ++i) {
		tgen_ensure(rems[i] < mods[i],
					"math: remainder must be smaller than the mod");
		crt = crt * detail::crt(rems[i], mods[i]);

		if (crt.a == -1)
			throw detail::there_is_no_in_range_error("congruent number", left,
													 right);
		if (crt.m > right) {
			if (!(left <= crt.a and crt.a <= right))
				throw detail::there_is_no_in_range_error("congruent number",
														 left, right);

			for (int j = 0; j < static_cast<int>(rems.size()); ++j)
				if (crt.a % mods[j] != rems[j])
					throw detail::there_is_no_in_range_error("congruent number",
															 left, right);
			return crt.a;
		}
	}

	uint64_t k_min = crt.a >= left ? 0 : ((left - crt.a) + crt.m - 1) / crt.m;
	uint64_t k_max = (right - crt.a) / crt.m;

	if (k_min > k_max)
		throw detail::there_is_no_in_range_error("congruent number", left,
												 right);

	return crt.a + next(k_min, k_max) * crt.m;
}

// O(log (right)).
// rem < mod.
inline uint64_t gen_congruent(uint64_t left, uint64_t right, uint64_t rem,
							  uint64_t mod) {
	return gen_congruent(left, right, std::vector<uint64_t>({rem}),
						 std::vector<uint64_t>({mod}));
}

// First congruent number >= left.
// O(|mods| + log (left)).
// |rems| = |mods|.
// rems_i < mods_i.
inline uint64_t congruent_from(uint64_t left, std::vector<uint64_t> rems,
							   std::vector<uint64_t> mods) {
	tgen_ensure(rems.size() == mods.size(),
				"math: number of remainders and mods must be the same");
	tgen_ensure(rems.size() > 0, "math: must have at least one congruence");

	detail::crt crt;
	for (int i = 0; i < static_cast<int>(rems.size()); ++i) {
		tgen_ensure(rems[i] < mods[i],
					"math: remainder must be smaller than the mod");
		crt = crt * detail::crt(rems[i], mods[i]);

		if (crt.a == -1)
			throw detail::there_is_no_from_error("congruent number", left);
		if (crt.m > std::numeric_limits<uint64_t>::max()) {
			if (crt.a < left)
				throw detail::error(
					"math: congruent number does not exist or is too large");

			for (int j = 0; j < static_cast<int>(rems.size()); ++j)
				if (crt.a % mods[j] != rems[j])
					throw detail::error("math: congruent number does "
										"not exist or is too large");
			return crt.a;
		}
	}

	uint64_t k = 0;
	if (crt.a < left)
		k = ((left - crt.a) + crt.m - 1) / crt.m;
	detail::i128 result = crt.a + k * crt.m;

	if (result > std::numeric_limits<uint64_t>::max())
		throw detail::error("math: congruent number is too large");
	return static_cast<uint64_t>(result);
}

// O(log (left))
// rem < mod.
inline uint64_t congruent_from(uint64_t left, uint64_t rem, uint64_t mod) {
	return congruent_from(left, std::vector<uint64_t>{rem},
						  std::vector<uint64_t>{mod});
}

// Last congruent number <= right.
// O(|mods| + log (right)).
// |rems| = |mods|.
// rems_i < mods_i.
inline uint64_t congruent_upto(uint64_t right, std::vector<uint64_t> rems,
							   std::vector<uint64_t> mods) {
	tgen_ensure(rems.size() == mods.size(),
				"math: number of remainders and mods must be the same");
	tgen_ensure(rems.size() > 0, "math: must have at least one congruence");

	detail::crt crt;
	for (int i = 0; i < static_cast<int>(rems.size()); ++i) {
		tgen_ensure(rems[i] < mods[i],
					"math: remainder must be smaller than the mod");

		crt = crt * detail::crt(rems[i], mods[i]);

		if (crt.a == -1)
			throw detail::there_is_no_upto_error("congruent number", right);
		if (crt.m > right) {
			if (!(crt.a <= right))
				throw detail::there_is_no_upto_error("congruent number", right);

			for (int j = 0; j < static_cast<int>(rems.size()); ++j)
				if (crt.a % mods[j] != rems[j])
					throw detail::there_is_no_upto_error("congruent number",
														 right);
			return crt.a;
		}
	}

	if (crt.a > right)
		throw detail::there_is_no_upto_error("congruent number", right);

	uint64_t k = (right - crt.a) / crt.m;
	detail::i128 result = crt.a + k * crt.m;

	if (result < 0)
		throw detail::there_is_no_upto_error("congruent number", right);
	return static_cast<uint64_t>(result);
}

// O(log r)
// rem < mod.
inline uint64_t congruent_upto(uint64_t right, uint64_t rem, uint64_t mod) {
	return congruent_upto(right, std::vector<uint64_t>{rem},
						  std::vector<uint64_t>{mod});
}

// Mod used for FFT/NTT.
inline constexpr int FFT_MOD = 998244353;

// Fibonacci sequence up to 2^64.
inline const std::vector<uint64_t> &fibonacci() {
	static const std::vector<uint64_t> fib = [] {
		std::vector<uint64_t> v = {0, 1};
		while (v.back() <=
			   std::numeric_limits<uint64_t>::max() - v[v.size() - 2])
			v.push_back(v.back() + v[v.size() - 2]);
		return v;
	}();
	return fib;
}

// Parition is ordered (composition), that is, (1, 1, 2) != (1, 2, 1).
// O(n).
// 0 < n.
// 0 < part_left.
inline std::vector<int>
gen_partition(int n, int part_left = 1,
			  std::optional<int> part_right = std::nullopt) {
	if (!part_right.has_value())
		part_right = n;
	part_right = std::min(*part_right, n);
	tgen_ensure(n > 0 and part_left > 0,
				"math: invalid parameters to gen_partition");
	tgen_ensure(part_left <= n and *part_right > 0, "math: no such partition");

	// dp[i] = log(numbers of ways to add to i).
	std::vector<long double> dp(n + 1, detail::LOG_ZERO);
	dp[0] = detail::LOG_ONE;
	long double window = detail::LOG_ZERO;
	for (int i = 1; i <= n; ++i) {
		if (i >= part_left)
			window = detail::add_log_space(window, dp[i - part_left]);
		if (i >= *part_right + 1)
			window = detail::sub_log_space(window, dp[i - *part_right - 1]);
		dp[i] = window;
	}
	tgen_ensure(dp[n] >= 0, "math: no such partition");

	// Crazy math tricks ahead.
	auto dp_pref = dp;
	for (int i = 1; i <= n; ++i)
		dp_pref[i] = detail::add_log_space(dp_pref[i - 1], dp[i]);

	std::vector<int> part;
	int sum = n;
	while (sum > 0) {
		// Will generate a number such that what remains is in [l, r].
		int l = std::max(0, sum - *part_right), r = sum - part_left;
		detail::tgen_ensure_against_bug(r >= 0, "math: r < 0 in gen_partition");

		int nxt_sum = std::min(sum, r);
		long double random = next<long double>(0, 1);

		// We generate a value X (log space), and then choose nxt_sum such
		// that dp_pref[nxt_sum-1] < X <= dp_pref[nxt_sum].

		// Math hack:
		// Let A = pref[l-1], B = pref[r], U = rand().
		// X = log[exp(A) + U * (exp(B) - exp(A))]
		//   = log{exp(B) * [exp(A) / exp(B) + U * (1 - exp(A) / exp(B))]}
		//   = B + log[exp(A - B) + U - U * exp(A - B))]
		//   = B + log[U + (1 - U) * exp(A - B)].
		long double val_l = l ? dp_pref[l - 1] : detail::LOG_ZERO,
					val_r = dp_pref[r];
		while (nxt_sum > l and
			   dp_pref[nxt_sum - 1] >=
				   val_r + detail::log_space(random +
											 (1 - random) * exp(val_l - val_r)))
			--nxt_sum;

		part.push_back(sum - nxt_sum);
		sum = nxt_sum;
	}

	return part;
}

// Parition is ordered (composition), that is, (1, 1, 2) != (1, 2, 1).
// O(n) time/memory if part_r is not set, O(n * k) time/memory otherwise.
// 0 < k <= n.
// 0 <= part_left.
inline std::vector<int>
gen_partition_fixed_size(int n, int k, int part_left = 0,
						 std::optional<int> part_right = std::nullopt) {
	if (!part_right.has_value())
		part_right = n;
	part_right = std::min(*part_right, n);
	tgen_ensure(0 < k and k <= n and part_left >= 0,
				"math: invalid parameters to gen_partition_fixed_size");
	tgen_ensure(static_cast<long long>(k) * part_left <= n and
					n <= static_cast<long long>(k) * (*part_right),
				"math: no such partition");

	// What we need to distribute to the parts.
	int s = n - k * part_left;

	std::vector<int> part(k);
	if (*part_right == n) {
		// Stars and bars - O(n).
		std::vector<int> cuts = {-1};

		int total = s + k - 1, bars = k - 1;
		for (int i = 0; i < total and bars > 0; ++i)
			if (next<long double>(0, 1) <
				static_cast<long double>(bars) / (total - i)) {
				cuts.push_back(i);
				--bars;
			}
		cuts.push_back(total);

		// Recovers parts.
		for (int i = 0; i < k; ++i)
			part[i] = cuts[i + 1] - cuts[i] - 1;
	} else {
		// DP with log trick - O(nk).
		int u = *part_right - part_left;

		// dp[i][j] = log(#ways to fill i parts with sum j)
		std::vector<std::vector<long double>> dp(
			k + 1, std::vector<long double>(s + 1, detail::LOG_ZERO));
		dp[0][0] = detail::LOG_ONE;

		for (int i = 1; i <= k; ++i) {
			std::vector<long double> pref = dp[i - 1];
			for (int j = 1; j <= s; ++j)
				pref[j] = detail::add_log_space(pref[j - 1], dp[i - 1][j]);

			for (int j = 0; j <= s; ++j) {
				dp[i][j] = pref[j];
				if (j >= u + 1)
					dp[i][j] = detail::sub_log_space(dp[i][j], pref[j - u - 1]);
			}
		}

		// Recovers parts backwards.
		int left_to_distribute = s;
		for (int i = k; i >= 1; --i) {
			long double log_total = detail::LOG_ZERO;
			for (int j = 0; j <= u and j <= left_to_distribute; ++j)
				log_total = detail::add_log_space(
					log_total, dp[i - 1][left_to_distribute - j]);
			detail::tgen_ensure_against_bug(
				log_total != detail::LOG_ZERO,
				"math: total == 0 in gen_partition_fixed_size");

			// Now we choose a number with probability proportional to
			// dp[i-1][.].

			// log(rand() * total) = log(rand()) + log(total).
			long double random =
				detail::log_space(next<long double>(0, 1)) + log_total;

			long double cur_prob = detail::LOG_ZERO;
			int chosen = 0;
			for (int j = 0; j <= u and j <= left_to_distribute; ++j) {
				cur_prob = detail::add_log_space(
					cur_prob, dp[i - 1][left_to_distribute - j]);
				if (random < cur_prob) {
					chosen = j;
					break;
				}
			}

			part[k - i] = chosen;
			left_to_distribute -= chosen;
		}
	}

	for (int &i : part)
		i += part_left;
	return part;
}

}; // namespace math

/**************
 *            *
 *   STRING   *
 *            *
 **************/

namespace detail {

/*
 * Regex.
 *
 * Compatible with testlib's regex.
 *
 * Operations:
 * - A single character yields itself ("a", "3").
 * - A list of characters inside square braces yields any a random element
 *   from the list ("[abc123]").
 * - A range of characters is equivalent to listing them ("[a-z1-9A-Z]").
 * - A pattern followed by {n} yields the pattern repeated n times ("a{3}").
 * - A pattern followed by {l,r} yields the pattern repeated between l and r
 *   times, uniformly at random ("a{3,5}").
 * - A list of patterns separated by | yields a random pattern from the
 *   list, uniformly at random ("abc|def|ghi").
 * - Parentheses can be used for grouping ("a((a|b){3})").
 *
 * Examples:
 * 1. str("[1-9][0-9]{1,2}") generates two- or three-digit numbers.
 * 2. str("a[b-d]{2}|e") generates "e" or a random string of length 3, with
 *                       the first character being 'a' and the second and
 *                       third characters being 'b', 'c', or 'd'.
 * 3. str("[1-9][0-9]{%d}", n-1) generates n-digit numbers.
 *
 * Operations defined by {n} and {l,r} are applied from left to right, and
 * the pattern that comes before has its delimiters defined either by () or
 * [] at its end or is taken from the beginning of the pattern (in
 * "a[bc]{2}", "{2}" is applied to "[bc]", and in "[01]abc{3}", the "{3}" is
 * appied to "[01]abc").
 */

// If it has children, it is either a SEQ or an OR group, defined by the
// pattern_ field.
struct regex_node {
	// Considered to be repetition of left_bound != -1, pattern if
	// children_.empty(), otherwise "SEQ" or "OR", defined by the pattern_
	// field.
	std::string
		pattern_; // Either pattern, or "SEQ" or "OR" (if !children_.empty()).
	std::vector<regex_node> children_; // Children, when SEQ or OR.
	int left_bound_, right_bound_; // Left and right bounds of the repetition,
								   // or -1 if not a repetition.
	double
		log_space_num_ways_; // Log space number of ways to match the pattern.
	std::optional<distinct_container<char>>
		distinct_; // Distinct generator for the pattern, for [chars].

	// c or [chars].
	regex_node(const std::string &pattern)
		: pattern_(pattern), left_bound_(-1), right_bound_(-1) {
		if (pattern.size() == 1) {
			log_space_num_ways_ = math::detail::LOG_ONE;
			return;
		}
		tgen_ensure_against_bug(pattern[0] == '[' and pattern.back() == ']',
								"str: invalid regex: expected character class");
		int size = pattern.size() - 2;
		log_space_num_ways_ = math::detail::log_space(size);
		distinct_ = distinct_container<char>(pattern.substr(1, size));
	}
	// SEQ or OR.
	regex_node(const std::string &pattern, std::vector<regex_node> &children)
		: pattern_(pattern), left_bound_(-1), right_bound_(-1) {
		if (pattern == "SEQ") {
			// Multiply the number of ways.
			log_space_num_ways_ = math::detail::LOG_ONE;
			for (const auto &child : children)
				log_space_num_ways_ += child.log_space_num_ways_;
		} else if (pattern == "OR") {
			// Add the number of ways.
			log_space_num_ways_ = math::detail::LOG_ZERO;
			for (const auto &child : children)
				log_space_num_ways_ = math::detail::add_log_space(
					log_space_num_ways_, child.log_space_num_ways_);
		} else
			tgen_ensure_against_bug("str: invalid regex: expected SEQ or OR");

		children_ = std::move(children);
		children.clear();
	}
	// REP.
	regex_node(int left_bound, int right_bound, regex_node &child)
		: pattern_("REP"), left_bound_(left_bound), right_bound_(right_bound) {
		log_space_num_ways_ = math::detail::LOG_ZERO;
		for (int i = left_bound; i <= right_bound; ++i)
			log_space_num_ways_ = math::detail::add_log_space(
				log_space_num_ways_, i * child.log_space_num_ways_);

		children_.push_back(std::move(child));
	}
};

// State of the regex parser.
struct regex_state {
	std::vector<regex_node> cur;	  // Current sequence of nodes.
	std::vector<regex_node> branches; // Branches of the current OR group.
};

// Creates a SEQ node from the current state.
inline regex_node make_regex_seq(regex_state &st) {
	return regex_node("SEQ", st.cur);
}

// Finishes current state.
inline regex_node finish_regex_state(regex_state &st) {
	// SEQ.
	if (st.branches.empty())
		return make_regex_seq(st);

	// OR.
	st.branches.push_back(make_regex_seq(st));
	return regex_node("OR", st.branches);
}

// Parses a regex pattern into a tree, computing the number of ways to match the
// pattern.
inline regex_node parse_regex(std::string regex) {
	std::string new_regex;
	for (char c : regex)
		if (c != ' ')
			new_regex += c;
	swap(regex, new_regex);
	regex_state cur;
	std::vector<regex_state> stack;

	for (size_t i = 0; i < regex.size(); ++i) {
		char c = regex[i];

		if (c == '(') {
			// Pushes the current state to the stack.
			stack.push_back(std::move(cur));
			cur = regex_state();
		} else if (c == ')') {
			// Finishes the current state, and adds it to the parent.
			regex_node node = finish_regex_state(cur);

			tgen_ensure(!stack.empty(), "str: invalid regex: unmatched `)`");
			cur = std::move(stack.back());
			stack.pop_back();

			cur.cur.push_back(std::move(node));
		} else if (c == '|') {
			// Starts a new OR group.
			regex_node node = make_regex_seq(cur);
			cur.branches.push_back(std::move(node));
		} else if (c == '[') {
			// Parses a character class.
			std::string chars;

			for (++i; i < regex.size() and regex[i] != ']'; ++i) {
				if (i + 2 < regex.size() and regex[i + 1] == '-') {
					char a = regex[i], b = regex[i + 2];
					if (a > b)
						std::swap(a, b);
					for (char x = a; x <= b; ++x)
						chars += x;
					i += 2;
				} else
					chars += regex[i];
			}

			tgen_ensure(i < regex.size() and regex[i] == ']',
						"str: invalid regex: unmatched `[`");
			cur.cur.emplace_back("[" + chars + "]");
		} else if (c == '{') {
			// Parses a repetition.
			++i;
			int l = -1, r = -1;

			while (i < regex.size() and
				   isdigit(static_cast<unsigned char>(regex[i]))) {
				if (l == -1)
					l = 0;
				tgen_ensure(l <= static_cast<int>(1e8),
							"str: invalid regex: number too large inside `{}`");
				l = 10 * l + (regex[i] - '0');
				++i;
			}

			if (i < regex.size() and regex[i] == ',') {
				++i;
				while (i < regex.size() and
					   isdigit(static_cast<unsigned char>(regex[i]))) {
					if (r == -1)
						r = 0;
					tgen_ensure(
						r <= static_cast<int>(1e8),
						"str: invalid regex: number too large inside `{}`");
					r = 10 * r + (regex[i] - '0');
					++i;
				}
			} else
				r = l;

			tgen_ensure(i < regex.size() and regex[i] == '}',
						"str: invalid regex: unmatched `{`");
			tgen_ensure(l != -1 and r != -1,
						"str: invalid regex: missing number inside `{}`");
			tgen_ensure(l <= r, "invalid regex: invalid range inside `{}`");

			// Creates a REP node from the previous node.
			tgen_ensure(!cur.cur.empty(),
						"str: invalid regex: expected expression before `{}`");

			regex_node rep(l, r, cur.cur.back());
			cur.cur.pop_back();
			cur.cur.push_back(std::move(rep));
		} else {
			// Creates a char node.
			cur.cur.emplace_back(std::string(1, c));
		}
	}

	tgen_ensure(stack.empty(), "str: invalid regex: unmatched `(`");
	return finish_regex_state(cur);
}

// Generates a uniformly random string that matches the given regex.
inline void gen_regex(const regex_node &node, std::string &str) {
	// For [chars], generate a random character from the list.
	if (node.pattern_[0] == '[') {
		str += node.pattern_[1 + next<int>(0, node.pattern_.size() - 3)];
		return;
	}

	// For REP, generate a random number of times to repeat the pattern.
	if (node.left_bound_ != -1) {
		// Generates a random value W from 0 to num_ways.
		// log(W) = log(random(0, 1) * num_ways)
		//        = log(random(0, 1)) + log(num_ways).
		double log_rand = math::detail::log_space(next<double>(0, 1)) +
						  node.log_space_num_ways_;
		double cur_prob = math::detail::LOG_ZERO;
		double child_num_ways = node.children_[0].log_space_num_ways_;

		for (int i = node.left_bound_; i <= node.right_bound_; ++i) {
			cur_prob =
				math::detail::add_log_space(cur_prob, i * child_num_ways);
			if (log_rand <= cur_prob) {
				for (int j = 0; j < i; ++j)
					gen_regex(node.children_[0], str);
				return;
			}
		}

		tgen_ensure_against_bug(false,
								"str: log_rand > cur_prob in REP gen_regex");
	}

	// For SEQ, generate all children.
	if (!node.children_.empty() and node.pattern_ == "SEQ") {
		for (const regex_node &child : node.children_)
			gen_regex(child, str);
		return;
	}

	// For OR, generate a random child.
	if (!node.children_.empty() and node.pattern_ == "OR") {
		// Generates a random value W from 0 to num_ways.
		// log(W) = log(random(0, 1) * num_ways)
		//        = log(random(0, 1)) + log(num_ways).
		double log_rand = math::detail::log_space(next<double>(0, 1)) +
						  node.log_space_num_ways_;
		double cur_prob = math::detail::LOG_ZERO;

		for (const regex_node &child : node.children_) {
			cur_prob = math::detail::add_log_space(cur_prob,
												   child.log_space_num_ways_);
			if (log_rand <= cur_prob) {
				gen_regex(child, str);
				return;
			}
		}

		tgen_ensure_against_bug(false,
								"str: log_rand > cur_prob in OR gen_regex");
	}

	// For char, generate the character.
	detail::tgen_ensure_against_bug(
		node.pattern_.size() == 1,
		"str: invalid regex: expected single character, but got `" +
			node.pattern_ + "`");
	str += node.pattern_[0];
}

// Formats a regex string with given arguments.
template <typename... Args>
std::string regex_format(const std::string &s, Args &&...args) {
	if constexpr (sizeof...(Args) == 0) {
		return s;
	} else {
		int size = std::snprintf(nullptr, 0, s.c_str(), args...) + 1;
		std::string buf(size, '\0');
		std::snprintf(buf.data(), size, s.c_str(), args...);
		buf.pop_back(); // remove '\0'
		return buf;
	}
}

} // namespace detail

/*
 * String generator.
 */

struct str : gen_base<str> {
	std::optional<list<char>> list_; // List of characters.
	std::optional<detail::regex_node>
		root_; // Root node of the regex tree for the whole string.

	// Creates generator for strings of size 'size', with random characters in
	// [value_left, value_right].
	str(int size, char value_left = 'a', char value_right = 'z')
		: list_(list<char>(size, value_left, value_right)) {}

	// Creates generator for strings of size 'size', with random characters in
	// 'chars'.
	str(int size, std::set<char> chars) : list_(list<char>(size, chars)) {}

	// Creates generator for strings that match the given regex.
	template <typename... Args> str(const std::string &regex, Args &&...args) {
		tgen_ensure(regex.size() > 0, "str: regex must be non-empty");

		root_ = detail::parse_regex(
			detail::regex_format(regex, std::forward<Args>(args)...));
	}

	// Restricts strings for str[idx] = value.
	str &fix(int idx, char character) {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		list_->fix(idx, character);
		return *this;
	}

	// Restricts strings for list[S] to be equal, for given subset S of indices.
	str &equal(std::set<int> indices) {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		list_->equal(indices);
		return *this;
	}

	// Restricts strings for str[idx_1] = str[idx_2].
	str &equal(int idx_1, int idx_2) {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		list_->equal(idx_1, idx_2);
		return *this;
	}

	// Restricts strings for str[left..right] to have all equal values.
	str &equal_range(int left, int right) {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		list_->equal_range(left, right);
		return *this;
	}

	// Restricts strings for all equal chars.
	str &all_equal() {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		list_->all_equal();
		return *this;
	}

	// Restricts strings for str[left..right] to be a palindrome.
	str &palindrome(int left, int right) {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		tgen_ensure(0 <= left and left <= right and right < list_->size_,
					"str: range indices must be valid");
		for (int i = left; i < right - (i - left); ++i)
			equal(i, right - (i - left));
		return *this;
	}

	// Restricts strings for the entire string to be a palindrome.
	str &palindrome() {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		return palindrome(0, list_->size_ - 1);
	}

	// Restricts strings for str[S] to be different (distinct), for given subset
	// S of indices.
	str &different(std::set<int> indices) {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		list_->different(indices);
		return *this;
	}

	// Restricts strings for str[idx_1] != str[idx_2].
	str &different(int idx_1, int idx_2) {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		list_->different(idx_1, idx_2);
		return *this;
	}

	// Restricts lists for list[left..right] to have all different chars.
	str &different_range(int left, int right) {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		list_->different_range(left, right);
		return *this;
	}

	// Restricts strings for all chars to be different.
	str &all_different() {
		tgen_ensure(!root_, "str: cannot add restriction for regex");
		list_->all_different();
		return *this;
	}

	// str value.
	struct value : gen_value_base<value> {
		using tgen_is_sequential_tag = detail::is_sequential_tag;
		using tgen_has_subset_defined_tag = detail::has_subset_defined_tag;

		using value_type = char;
		using std_type = std::string;
		std::string str_;

		value(const std::string &str) : str_(str) {
			tgen_ensure(!str_.empty(), "str: value: cannot be empty");
		}

		// Fetches size.
		int size() const { return str_.size(); }

		// Fetches position idx.
		char &operator[](int idx) {
			tgen_ensure(0 <= idx and idx < size(),
						"str: value: index out of bounds");
			return str_[idx];
		}
		const char &operator[](int idx) const {
			tgen_ensure(0 <= idx and idx < size(),
						"str: value: index out of bounds");
			return str_[idx];
		}

		// Sorts characters in non-decreasing order.
		// O(n log n).
		value &sort() {
			std::sort(str_.begin(), str_.end());
			return *this;
		}

		// Reverses string.
		// O(n).
		value &reverse() {
			std::reverse(str_.begin(), str_.end());
			return *this;
		}

		// Lowercases all characters.
		// O(n).
		value &lowercase() {
			for (char &c : str_)
				c = std::tolower(c);
			return *this;
		}

		// Uppercases all characters.
		// O(n).
		value &uppercase() {
			for (char &c : str_)
				c = std::toupper(c);
			return *this;
		}

		// Concatenates two values.
		// Linear.
		value operator+(const value &rhs) const {
			return value(str_ + rhs.str_);
		}

		// Prints to std::ostream.
		friend std::ostream &operator<<(std::ostream &out, const value &val) {
			return out << val.str_;
		}

		// Gets a std::string representing the value.
		std::string to_std() const { return str_; }
	};

	// Generates str value.
	// If created from restrictions: O(n log n).
	// If created from regex: expected linear.
	value gen() const {
		if (root_) {
			// Regex.
			std::string ret_str;
			gen_regex(*root_, ret_str);
			return value(ret_str);
		} else {
			// List.
			std::vector<char> vec = list_->gen().to_std();
			return value(std::string(vec.begin(), vec.end()));
		}
	}
};

/************
 *          *
 *   PAIR   *
 *          *
 ************/

namespace detail {

// Generates pair first == second.
// O(1).
template <typename T> std::pair<T, T> gen_eq(T L1, T R1, T L2, T R2) {
	T L = std::max(L1, L2);
	T R = std::min(R1, R2);

	tgen_ensure(L <= R, "pair: no valid values to generate");
	T x = next<T>(L, R);
	return {x, x};
}

// Returns {R1-L1+1, R2-L2+1}.
template <typename T>
std::pair<u128, u128> get_n_and_m(T L1, T R1, T L2, T R2) {
	u128 n = static_cast<i128>(R1) - L1 + 1;
	u128 m = static_cast<i128>(R2) - L2 + 1;
	return {n, m};
}

// Returns first + first+1 + ... + last,
// num_term terms. Avoids overflow.
static u128 pos_arith_sum(u128 first, u128 last, u128 num_terms) {
	u128 x = first + last, y = num_terms;

	// x * y / 2, avoiding overflow.
	if (x % 2 == 0)
		x /= 2;
	else
		y /= 2;

	return x * y;
}

// Generates pair first != second.
// O(1) expected.
template <typename T> std::pair<T, T> gen_neq(T L1, T R1, T L2, T R2) {
	auto [n, m] = get_n_and_m(L1, R1, L2, R2);

	T L_intersect = std::max(L1, L2);
	T R_intersect = std::min(R1, R2);
	u128 inter = static_cast<i128>(R_intersect) - L_intersect + 1;

	u128 total = n * m - inter;
	tgen_ensure(total > 0, "pair: no valid values to generate");

	// Runs O(1) expected times in the worst case.
	T a, b;
	do {
		a = next<T>(L1, R1);
		b = next<T>(L2, R2);
	} while (a == b);

	return {a, b};
}

// For lt, splits 'second' into two regions:
// 1) second <= R1 -> number of 'first' is (second - L1)
// 2) second >  R1 -> number of 'first' is (R1 - L1 + 1)
// Returns {count_region1, count_region2}.
// O(1).
template <typename T>
std::pair<u128, u128> count_lt_regions(T L1, T R1, T L2, T R2) {
	auto [n, m] = get_n_and_m(L1, R1, L2, R2);

	// 'second' must be >= L1 + 1.
	i128 L_second = std::max<i128>(L2, static_cast<i128>(L1) + 1);
	i128 R_second = R2;

	// Split point for 'second'.
	i128 split = std::min<i128>(R_second, R1);

	// Region 1: b in [L_second, split].
	u128 len1 = std::max<i128>(0, split - L_second + 1);

	u128 count_region1 = 0;
	if (len1 > 0) {
		// For b in [L_second, split], there are (b - L1) ways.
		i128 first = L_second - L1;
		i128 last = split - L1;

		// Arithmetic series first + (first + 1) + ... + last, len1 terms.
		count_region1 = pos_arith_sum(first, last, len1);
	}

	// Region 2: b > R1.
	// For b in [R1+1, R_second], there are 'n' ways.
	i128 L_second_region2 = std::max(L_second, static_cast<i128>(R1) + 1);

	u128 len2 = std::max<i128>(0, R_second - L_second_region2 + 1);
	u128 count_region2 = len2 * n;

	return {count_region1, count_region2};
}

// Generates pair first < second.
// O(log(R1 - L1 + 1) + log(R2 - L2 + 1)).
template <typename T> std::pair<T, T> gen_lt(T L1, T R1, T L2, T R2) {
	auto [n, m] = get_n_and_m(L1, R1, L2, R2);

	// 'second' needs to be at least L1 + 1 to have a valid value for
	// 'first'.
	i128 L_second = std::max<i128>(L2, static_cast<i128>(L1) + 1);
	i128 R_second = R2;

	// Splits 'second' into two regions:
	// 1) b <= R1 -> number of 'first' is (b - L1);
	// 2) b >  R1 -> number of 'first' is (R1 - L1 + 1).
	i128 split = std::min<i128>(R_second, R1);

	auto [count_region1, count_region2] = count_lt_regions(L1, R1, L2, R2);
	u128 total = count_region1 + count_region2;
	tgen_ensure(total > 0, "pair: no valid values to generate");

	u128 k = detail::next128(total);
	if (k < count_region1) {
		// Region 1: invert arithmetic series.

		// For b in [L_second, split].
		u128 len1 = std::max<i128>(0, split - L_second + 1);

		// We consider b in [L_second, L_second + d].
		// Each b contributes (b - L1) = base + (b - L_second).
		// So we sum: base + (base+1) + ... + (base+d)
		// d in [0, len1).

		i128 base = L_second - L1;
		i128 lo = 0, hi = static_cast<i128>(len1) - 1;

		while (lo < hi) {
			i128 mid = lo + (hi - lo) / 2;

			if (pos_arith_sum(base, base + mid, mid + 1) <= k)
				lo = mid + 1;
			else
				hi = mid;
		}
		i128 d = lo;

		// Subtracts prefix sum with d-1 terms from k.
		if (d > 0)
			k -= pos_arith_sum(base, base + d - 1, d);

		return {L1 + static_cast<T>(k), L_second + d};
	} else {
		// Region 2: uniform block of size n.
		k -= count_region1;

		// For b in [R1+1, R_second], there are 'n' ways.
		i128 L_second_region2 = std::max(L_second, static_cast<i128>(R1) + 1);

		return {L1 + static_cast<T>(k % n),
				L_second_region2 + static_cast<T>(k / n)};
	}
}

// Generates pair first > second.
// O(log(R1 - L1 + 1) + log(R2 - L2 + 1)).
template <typename T> std::pair<T, T> gen_gt(T L1, T R1, T L2, T R2) {
	auto [first, second] = gen_lt(L2, R2, L1, R1);
	return {second, first};
}

// Generates pair first <= second.
// O(log(R1 - L1 + 1) + log(R2 - L2 + 1)).
template <typename T> std::pair<T, T> gen_leq(T L1, T R1, T L2, T R2) {
	// Counts how many pairs are there with first = second.
	i128 L_intersect = std::max(L1, L2);
	i128 R_intersect = std::min(R1, R2);
	u128 eq_count = std::max<i128>(0, R_intersect - L_intersect + 1);

	// Counts how many pairs are there with first < second.
	auto [lt_region1, lt_region2] = count_lt_regions(L1, R1, L2, R2);
	u128 lt_count = lt_region1 + lt_region2;

	u128 total = eq_count + lt_count;
	tgen_ensure(total > 0, "pair: no valid values to generate");

	if (detail::next128(total) < eq_count)
		return gen_eq(L1, R1, L2, R2);
	return gen_lt(L1, R1, L2, R2);
}

// Generates pair first >= second.
// O(log(R1 - L1 + 1) + log(R2 - L2 + 1)).
template <typename T> std::pair<T, T> gen_geq(T L1, T R1, T L2, T R2) {
	auto [first, second] = gen_leq(L2, R2, L1, R1);
	return {second, first};
}

}; // namespace detail

/*
 * Pair generator.
 *
 * Pairs of integral types.
 */

template <typename T> struct pair : gen_base<pair<T>> {
	std::pair<T, T> first_, second_; // Range of first and second values.
	// Type of restriction.
	enum class restriction_type { eq, neq, lt, gt, leq, geq, unspecified };
	restriction_type type_ = restriction_type::unspecified;

	// Creates a pair with random values in [first_l, first_r] and [second_l,
	// second_r].
	pair(T first_left, T first_right, T second_left, T second_right)
		: first_(first_left, first_right), second_(second_left, second_right) {
		tgen_ensure(first_left <= first_right,
					"pair: first range must be valid");
		tgen_ensure(second_left <= second_right,
					"pair: second range must be valid");
	}

	// Creates a pair with random values in [both_l, both_r].
	pair(T both_left, T both_right)
		: pair(both_left, both_right, both_left, both_right) {}

	// Restricts pair for first = second.
	pair &eq() {
		type_ = restriction_type::eq;
		return *this;
	}

	// Restricts pair for first != second.
	pair &neq() {
		type_ = restriction_type::neq;
		return *this;
	}

	// Restricts pair for first < second.
	pair &lt() {
		type_ = restriction_type::lt;
		return *this;
	}

	// Restricts pair for first > second.
	pair &gt() {
		type_ = restriction_type::gt;
		return *this;
	}

	// Restricts pair for first <= second.
	pair &leq() {
		type_ = restriction_type::leq;
		return *this;
	}

	// Restricts pair for first >= second.
	pair &geq() {
		type_ = restriction_type::geq;
		return *this;
	}

	// Pair value.
	struct value : gen_value_base<value> {
		using value_type = T;
		using std_type = std::pair<T, T>;

		std::pair<T, T> pair_;
		char sep_;

		value(const std::pair<T, T> &pair) : pair_(pair), sep_(' ') {}
		value(const T &first, const T &second)
			: pair_(first, second), sep_(' ') {}

		T first() const { return pair_.first; }
		T second() const { return pair_.second; }

		// Sets the separator for the pair, for printing.
		value &separator(char sep) {
			sep_ = sep;
			return *this;
		}

		// Prints to std::ostream, separated by sep_.
		friend std::ostream &operator<<(std::ostream &out, const value &val) {
			return out << val.pair_.first << val.sep_ << val.pair_.second;
		}

		// Gets a std::pair representing the value.
		auto to_std() const {
			if constexpr (!is_generator_value<T>::value) {
				return pair_;
			} else {
				std::pair<typename T::std_type, typename T::std_type> pair(
					pair_.first.to_std(), pair_.second.to_std());
				return pair;
			}
		}
	};

	// Generates a random pair.
	// O(log(R1 - L1 + 1) + log(R2 - L2 + 1)).
	value gen() const {
		T L1 = first_.first, R1 = first_.second;
		T L2 = second_.first, R2 = second_.second;

		switch (type_) {
		case restriction_type::unspecified:
			return {next<T>(L1, R1), next<T>(L2, R2)};
		case restriction_type::eq:
			return detail::gen_eq<T>(L1, R1, L2, R2);
		case restriction_type::neq:
			return detail::gen_neq<T>(L1, R1, L2, R2);
		case restriction_type::lt:
			return detail::gen_lt<T>(L1, R1, L2, R2);
		case restriction_type::gt:
			return detail::gen_gt<T>(L1, R1, L2, R2);
		case restriction_type::leq:
			return detail::gen_leq<T>(L1, R1, L2, R2);
		case restriction_type::geq:
			return detail::gen_geq<T>(L1, R1, L2, R2);
		}
		throw detail::error("pair: unknown restriction type");
	}
};

/************
 *          *
 *   TREE   *
 *          *
 ************/

namespace detail {

// Generates edges from Prufer sequence.
// O(n).
inline std::vector<std::pair<int, int>> edges_from_prufer(std::vector<int> p) {
	int n = p.size() + 2;

	// Degrees.
	std::vector<int> d(n, 1);
	for (int i : p)
		d[i]++;

	// Adds last vertex.
	p.push_back(n - 1);

	// Finds first vertex with degree 1.
	int idx, u;
	idx = u = find(d.begin(), d.end(), 1) - d.begin();

	// Generates edges.
	std::vector<std::pair<int, int>> edges;
	for (int v : p) {
		edges.emplace_back(u, v);
		if (--d[v] == 1 and v < idx)
			u = v;
		else
			idx = u = find(d.begin() + idx + 1, d.end(), 1) - d.begin();
	}
	return edges;
}

// Disjoint set union (union-find) for connectivity queries.
struct dsu {
	std::vector<int> parent_;
	std::vector<unsigned char> rank_;

	// Creates a dsu with `n` elements, indexed from 0 to n-1.
	// Initially every element is in its own set.
	// O(n).
	dsu(int n) : parent_(n), rank_(n, 0) {
		for (int i = 0; i < n; ++i)
			parent_[i] = i;
	}

	// Adds new elements fo the dsu, each in their own new set.
	// O(k) amortized.
	void add_elements(int k) {
		for (int i = 0; i < k; ++i) {
			int new_id = parent_.size();
			parent_.push_back(new_id);
			rank_.push_back(0);
		}
	}

	// Finds representative of set containing i.
	// O(alpha(n)) amortized, O(log n) worst case.
	int find(int i) {
		return parent_[i] == i ? i : parent_[i] = find(parent_[i]);
	}

	// Merges components of `a` and `b`. Returns if the sets were united, and
	// false if a and be were in the same set.
	// O(alpha(n)) amortized, O(log n) worst case.
	bool unite(int a, int b) {
		a = find(a);
		b = find(b);
		if (a == b)
			return false;
		if (rank_[a] > rank_[b])
			std::swap(a, b);
		parent_[a] = b;
		if (rank_[a] == rank_[b])
			++rank_[b];
		return true;
	}
};

} // namespace detail

/*
 * Tree generator.
 *
 * Unrooted trees with `n` vertices, indexed from 0 to n-1.
 * These are unrooted undirected labeled trees, that is, isomorphism is not
 * taken into account. VWeight is the type of vertex weights, and EWeight are
 * the type of edge weights. Generator does not generate weights. The weights
 * are to be set in the wtree::value.
 */
template <typename VWeight, typename EWeight>
struct wtree : gen_base<wtree<VWeight, EWeight>> {
	int n_;								  // Number of vertices.
	std::set<std::pair<int, int>> edges_; // Edges that were set.

	// Creates tree generator with `n` vertices.
	// O(1).
	wtree(int n) : n_(n) { tgen_ensure(n > 0, "wtree: n must be positive"); }

	// Adds edge bewteen u and v (this edge must be generated).
	// O(log n).
	wtree &add_edge(int u, int v) {
		tgen_ensure(0 <= std::min(u, v) and std::max(u, v) < n_,
					"wtree: vertices must be index in [0, n)");
		tgen_ensure(u != v, "wtree: cannot add self loop to tree");

		if (u > v)
			std::swap(u, v);
		edges_.emplace(u, v);
		return *this;
	}

	// Tree value.
	struct value {
		int n_;									 // Number of vertices.
		std::vector<std::set<int>> adj_;		 // Adjacency list.
		std::vector<std::pair<int, int>> edges_; // Edge list.
		bool add_1_; // If should add 1 for printing vertex ids.
		std::optional<int>
			print_parents_; // If should in parent style (stores the root).
		std::optional<std::vector<VWeight>> vertex_weights_; // Vertex weights.
		std::optional<std::vector<EWeight>>
			edge_weights_; // Edge weights (in same order as edges_).
		detail::dsu dsu_;  // Connectivity of current edges (for cycle checks).

		// Creates value from `n` and adjacecy list.
		// O(n).
		value(int n, const std::vector<std::set<int>> &adj)
			: n_(n), adj_(adj), add_1_(false), dsu_(n) {
			tgen_ensure(static_cast<int>(adj.size()) == n,
						"wtree: value: size of adjacency list should ne `n`");

			for (int u = 0; u < n; ++u)
				for (auto v : adj[u]) {
					tgen_ensure(
						0 <= v and v < n,
						"wtree: value: vertices must be indexed in [0, n)");
					// Symmetric adjacency: count each undirected edge once.
					if (u < v) {
						edges_.emplace_back(u, v);
						tgen_ensure(
							dsu_.unite(u, v),
							"wtree: value: initial adjacency must form a tree");
					}
				}
		}

		// Creates value from `n` and edge list.
		// O(n).
		value(int n, const std::vector<std::pair<int, int>> &edges)
			: n_(n), adj_(n), edges_(edges), add_1_(false), dsu_(n) {
			for (auto [u, v] : edges) {
				tgen_ensure(
					0 <= std::min(u, v) and std::max(u, v) < n,
					"wgraph: value: vertices must be indexed in [0, n)");
				tgen_ensure(dsu_.unite(u, v),
							"wtree: value: initial edges must form a tree");
				adj_[u].insert(v);
				adj_[v].insert(u);
			}
		}
		value(int n, const std::set<std::pair<int, int>> &edges)
			: value(n, std::vector<std::pair<int, int>>(edges.begin(),
														edges.end())) {}

		// Weight type converstion.
		// O(n).
		template <typename NewVWeight, typename NewEWeight>
		typename wtree<NewVWeight, NewEWeight>::value
		convert_weight_types() const {
			tgen_ensure(!vertex_weights_.has_value() and
							!edge_weights_.has_value(),
						"wtree: value: cannot convert weight type after "
						"assigning weights");

			typename wtree<NewVWeight, NewEWeight>::value new_tree(n_, adj_);
			new_tree.add_1_ = add_1_;
			new_tree.print_parents_ = print_parents_;
			return new_tree;
		}

		// Fetches number of vertices.
		int n() const { return n_; }

		// Fetches a const ref. to adjacency list.
		const std::vector<std::set<int>> &adj() const { return adj_; }

		// Fetches a const ref. to edge list.
		const std::vector<std::pair<int, int>> &edges() const { return edges_; }

		// Fetches a const ref. to vertex weights.
		const std::optional<std::vector<VWeight>> &vertex_weights() const {
			return vertex_weights_;
		}

		// Fetches a const ref. to edge weights.
		const std::optional<std::vector<EWeight>> &edge_weights() const {
			return edge_weights_;
		}

		// Sets vertex weights.
		// O(n).
		template <typename NewVWeight = VWeight>
		typename wtree<NewVWeight, EWeight>::value set_vertex_weights(
			const std::vector<NewVWeight> &vertex_weights) const {
			tgen_ensure(static_cast<int>(vertex_weights.size()) == n(),
						"wtree: value: must give `n` vertex weights");

			auto new_tree = convert_weight_types<NewVWeight, EWeight>();
			new_tree.vertex_weights_ = vertex_weights;
			return new_tree;
		}

		// Sets edge weights.
		// O(n).
		template <typename NewEWeight = EWeight>
		typename wtree<VWeight, NewEWeight>::value
		set_edge_weights(const std::vector<NewEWeight> &edge_weights) const {
			tgen_ensure(static_cast<int>(edge_weights.size()) == edges().size(),
						"wtree: value: must give `m` edge weights");

			auto new_tree = convert_weight_types<VWeight, NewEWeight>();
			new_tree.edge_weights_ = edge_weights;
			return new_tree;
		}

		// Adds 1 to vertex ids, for printing.
		// O(1).
		value &add_1() {
			add_1_ = true;
			return *this;
		}

		// Prints the tree in parent style.
		// If foot = -1, the root is considered to be 0, and its parent is not
		// printed. Otherwise, prints the parent of the root as -1. If root = n,
		// randomizes the root. O(1).
		value &print_parents(int root = -1) {
			tgen_ensure(root == -1 or (0 <= root and root < n() or root == n()),
						"wtree: value: root must -1, `n`, or in [0, n)");
			print_parents_ = root;
			return *this;
		}

		// Shuffles the tree's vertex labels (except those in `indices`,
		// which keep their current label) and edge order. The change is
		// applied eagerly to the underlying adjacency list, edge list,
		// vertex weights and edge weights.
		// O(n).
		value &shuffle_except(std::set<int> indices) {
			// Builds the relabeling: for each vertex `i`, `new_label[i]` is
			// its new id. Vertices in `indices` keep their label; the others
			// are permuted among themselves.
			std::vector<int> new_label(n());
			std::vector<int> shuffled;
			for (int i = 0; i < n(); ++i) {
				if (indices.count(i))
					new_label[i] = i;
				else
					shuffled.push_back(i);
			}
			std::vector<int> targets = shuffled;
			tgen::shuffle(targets.begin(), targets.end());
			for (size_t k = 0; k < shuffled.size(); ++k)
				new_label[shuffled[k]] = targets[k];

			// Rewrites adjacency list with new labels.
			std::vector<std::set<int>> new_adj(n());
			for (int u = 0; u < n(); ++u)
				for (int v : adj_[u])
					new_adj[new_label[u]].insert(new_label[v]);
			adj_ = std::move(new_adj);

			// Rewrites edges with new labels (canonical undirected order).
			for (auto &[u, v] : edges_) {
				u = new_label[u];
				v = new_label[v];
				if (u > v)
					std::swap(u, v);
			}

			// Permutes vertex weights to match the new labels.
			if (vertex_weights_.has_value()) {
				std::vector<VWeight> new_vw(n());
				for (int i = 0; i < n(); ++i)
					new_vw[new_label[i]] = (*vertex_weights_)[i];
				vertex_weights_ = std::move(new_vw);
			}

			// Rebuilds the dsu so future `add_edge` calls see the new labels.
			dsu_ = detail::dsu(n());
			for (auto [u, v] : edges_)
				dsu_.unite(u, v);

			// Shuffles edge order, keeping edge weights aligned.

			std::vector<int> perm(edges_.size());
			std::iota(perm.begin(), perm.end(), 0);
			tgen::shuffle(perm.begin(), perm.end());

			std::vector<std::pair<int, int>> new_edges;
			std::optional<std::vector<EWeight>> new_ew;
			if (edge_weights_.has_value())
				new_ew = std::vector<EWeight>();
			for (int i : perm) {
				new_edges.push_back(edges_[i]);
				if (new_ew.has_value())
					new_ew->push_back((*edge_weights_)[i]);
			}
			edges_ = new_edges;
			if (new_ew.has_value())
				edge_weights_ = new_ew;

			return *this;
		}

		// Shuffles the tree's vertices and edge order.
		// O(n).
		value &shuffle() { return shuffle_except({}); }

		// Adds `k` vertices to the graph (labeled n, n+1, ...n+k-1). Updates
		// `n` accordingly. This makes the tree invalid (not a tree anymore).
		// O(k) amortized.
		value &add_vertices(int k, std::optional<std::vector<VWeight>>
									   new_vertex_weights = std::nullopt) {
			n_ += k;
			adj_.resize(n());
			if (new_vertex_weights.has_value()) {
				tgen_ensure(vertex_weights().has_value(),
							"wtree: value: cannot add weighted vertices to "
							"vertex-unweighted graph");
				tgen_ensure(
					static_cast<int>(new_vertex_weights->size()) == k,
					"wtree: value: number of vertex weights must be equal "
					"to number of added vertices");

				vertex_weights_->insert(vertex_weights_->end(),
										new_vertex_weights->begin(),
										new_vertex_weights->end());
			} else
				tgen_ensure(!vertex_weights().has_value(),
							"wtree: value: cannot add unweighted vertices to "
							"vertex-weighted graph");

			dsu_.add_elements(k);

			return *this;
		}

		// Adds edge (u, v).
		// O(log n) amortized.
		value &add_edge(int u, int v, std::optional<EWeight> w = std::nullopt) {
			tgen_ensure(0 <= std::min(u, v) and std::max(u, v) < n(),
						"wtree: value: vertex ids must be valid");

			if (u > v)
				std::swap(u, v);

			if (adj_[u].count(v))
				return *this;

			adj_[u].insert(v);
			adj_[v].insert(u);
			edges_.emplace_back(u, v);
			tgen_ensure(dsu_.unite(u, v),
						"wtree: value: added edge must not create a cycle");

			if (w.has_value()) {
				tgen_ensure(edge_weights().has_value(),
							"wtree: value: cannot add weighted edge to "
							"edge-unweighted graph");

				edge_weights_->push_back(*w);
			} else
				tgen_ensure(!edge_weights().has_value(),
							"wtree: value: cannot add unweighted edge to "
							"edge-weighted graph");

			return *this;
		}

		// Links tree with another `rhs`, adding the edge between u (in left
		// tree) and v (in right tree). Ids for added vertices are updated
		// accordingly.
		// O(rhs.n + rhs.m * log n) amortized.
		value &link(const value &rhs, int new_u, int new_v,
					std::optional<EWeight> new_w = std::nullopt) {
			tgen_ensure(0 <= new_u and new_u < n() and 0 <= new_v and
							new_v < rhs.n(),
						"wtree: value: vertex ids must be valid");

			// Edges from right-hand side.
			int shift = n();
			add_vertices(rhs.n(), rhs.vertex_weights());
			for (int i = 0; i < rhs.edges().size(); ++i) {
				auto [u, v] = rhs.edges()[i];
				add_edge(shift + u, shift + v,
						 rhs.edge_weights().has_value()
							 ? std::optional<EWeight>((*rhs.edge_weights())[i])
							 : std::nullopt);
			}

			// New edge.
			add_edge(new_u, shift + new_v, new_w);

			return *this;
		}

		// Glues the tree with another `rhs` such that index_pairs[i].first is
		// considered to be the same as index_pairs[i].second. Ids for added
		// vertices are updated accordingly.
		// O(rhs.n + rhs.m * log n) amortized.
		value &glue(const value &rhs,
					std::set<std::pair<int, int>> index_pairs) {
			// Checks validity of indices.
			std::set<int> idx_left, idx_right;
			std::vector<int> right_id_to_left(rhs.n(), -1);
			for (auto [l, r] : index_pairs) {
				tgen_ensure(
					0 <= l and l < n() and 0 <= r and r < rhs.n(),
					"wtree: value: vertex indices to glue must be valid");
				tgen_ensure(idx_left.count(l) == 0 and idx_right.count(r) == 0,
							"wtree: value: must not have repeated indices "
							"on the same side to glue");

				idx_left.insert(l);
				idx_right.insert(r);
				right_id_to_left[r] = l;
			}

			// Computes new ids of right vertices.
			std::vector<int> new_right_id(rhs.n(), -1);
			int intersection_lt = 0;
			std::optional<std::vector<VWeight>> rhs_vertex_weights;
			for (int i = 0; i < rhs.n(); ++i) {
				if (right_id_to_left[i] != -1) {
					// Is in intersecion.
					++intersection_lt;
					new_right_id[i] = right_id_to_left[i];
				} else {
					// New id.
					new_right_id[i] = n() + i - intersection_lt;
					if (rhs.vertex_weights().has_value()) {
						if (!rhs_vertex_weights.has_value())
							rhs_vertex_weights = std::vector<VWeight>();
						rhs_vertex_weights->push_back(
							(*rhs.vertex_weights())[i]);
					}
				}
			}

			// Adds new vertices and edges.
			add_vertices(rhs.n() - intersection_lt, rhs_vertex_weights);
			for (int i = 0; i < rhs.edges().size(); ++i) {
				auto [u, v] = rhs.edges()[i];
				add_edge(new_right_id[u], new_right_id[v],
						 rhs.edge_weights().has_value()
							 ? std::optional<EWeight>((*rhs.edge_weights())[i])
							 : std::nullopt);
			}

			return *this;
		}
		value &glue(const value &rhs,
					std::initializer_list<std::pair<int, int>> il) {
			return glue(rhs, std::set<std::pair<int, int>>(il));
		}

		// Glues the tree with another `rhs` at `indices`. That is, idx in
		// `indices` are considered to be the same vertex. Ids for added
		// vertices are updated accordingly.
		// O(rhs.n).
		value &glue(const value &rhs, std::set<int> indices) {
			std::set<std::pair<int, int>> index_pairs;
			for (auto i : indices)
				index_pairs.emplace(i, i);
			return glue(rhs, index_pairs);
		}
		value &glue(const value &rhs, const std::initializer_list<int> &il) {
			return glue(rhs, std::set<int>(il));
		}

		// Prints to std::ostream.
		// O(n).
		friend std::ostream &operator<<(std::ostream &out, const value &val) {
			// Prints vertex weights.
			if (val.vertex_weights()) {
				for (int i = 0; i < val.n(); ++i) {
					if (i > 0)
						out << " ";
					out << (*val.vertex_weights())[i];
				}
				out << std::endl;
			}

			tgen_ensure(val.edges().size() == val.n() - 1,
						"wtree: value: invalid tree to print (number of edges "
						"must be `n` - 1)");

			// Prints in parent style.
			if (val.print_parents_.has_value()) {
				tgen_ensure(!val.edge_weights().has_value(),
							"wtree: value: cannot print parent style if edges "
							"are weighted");

				int root = *val.print_parents_;
				bool skip_parent_0 = root == -1;
				if (root == -1)
					root = 0;
				if (root == val.n())
					root = next(0, val.n() - 1);

				std::vector<int> parent(val.n(), -1);

				std::queue<int> q;
				std::vector<int> vis(val.n(), false);
				q.push(root);
				vis[root] = true;

				while (q.size()) {
					int u = q.front();
					q.pop();
					for (int v : val.adj()[u])
						if (!vis[v]) {
							vis[v] = true;
							q.push(v);
							parent[v] = u;
						}
				}

				if (skip_parent_0) {
					for (int i = 1; i < val.n(); ++i) {
						tgen_ensure(
							parent[i] < i,
							"wtree: value: parent of i must be less than i for "
							"printing in parent style if root is -1");

						if (i > 1)
							out << " ";
						out << parent[i] + val.add_1_;
					}
				} else {
					for (int i = 0; i < val.n(); ++i) {
						if (i > 0)
							out << " ";
						out << (parent[i] == -1 ? -1 : parent[i]) + val.add_1_;
					}
				}

				out << std::endl;
				return out;
			}

			// Prints edges.
			for (int i = 0; i < val.edges().size(); ++i) {
				auto [u, v] = val.edges()[i];
				out << (u + val.add_1_) << " " << (v + val.add_1_);

				// Edge weight.
				if (val.edge_weights().has_value())
					out << " " << (*val.edge_weights())[i];

				out << std::endl;
			}

			return out;
		}

		// Gets a std::pair<n, adj> representing the value.
		std::pair<int, std::vector<std::set<int>>> to_std() const {
			return std::pair(n_, adj_);
		}
	};

	// Generates tree value.
	// O(n).
	value gen() const {
		// Constructs adjacency list.
		std::vector<std::vector<int>> adj(n_);
		for (auto [u, v] : edges_) {
			adj[u].push_back(v);
			adj[v].push_back(u);
		}

		std::vector<int> comp_size;
		std::vector<std::vector<int>> component_ids;
		std::vector<bool> vis(n_, false);
		std::queue<int> q;

		for (int i = 0; i < n_; ++i) {
			if (vis[i])
				continue;

			vis[i] = true;
			q.push(i);
			comp_size.push_back(0);
			component_ids.emplace_back();
			while (q.size()) {
				int u = q.front();
				q.pop();
				++comp_size.back();
				component_ids.back().push_back(u);
				for (int v : adj[u]) {
					if (!vis[v]) {
						vis[v] = true;
						q.push(v);
					}
				}
			}
		}

		// Creates edges connecting the connected components by treating them as
		// vertices.
		std::vector<std::pair<int, int>> new_edges(edges_.begin(),
												   edges_.end());
		if (comp_size.size() > 1) {
			std::vector<int> prufer_values =
				many_by_distribution(comp_size.size() - 2, comp_size);
			for (auto [u, v] : detail::edges_from_prufer(prufer_values))
				new_edges.emplace_back(pick(component_ids[u]),
									   pick(component_ids[v]));
		}

		return value(n_, new_edges);
	}

	// Skewed tree.
	// Vertex 0 is the root. For each i in 1 .. n-1, parent(i) is
	// wnext(i, elongation), i.e. a value in [0, i) with skew controlled by
	// elongation (see wnext).
	// Preset edges are not supported.
	// If elongation is small enough, generates a star (center 0).
	// If elongation is large enough, generates a path (endpoints 0 and n-1).
	// O(n).
	value get_skewed(int elongation) const {
		tgen_ensure(edges_.empty(),
					"wtree: get_skewed does not support preset edges");

		std::vector<std::pair<int, int>> edges;
		for (int i = 1; i < n_; ++i)
			edges.emplace_back(i, wnext<int>(i, elongation));
		return value(n_, edges);
	}
};

/*
 * Other types of weighted-ness.
 */

// Vertex weighted graph.
template <typename VWeight> using vtree = wtree<VWeight, int>;

// Edge weighted graph.
template <typename EWeight> using etree = wtree<int, EWeight>;

// Unweighted graph.
using tree = wtree<int, int>;

/*************
 *           *
 *   GRAPH   *
 *           *
 *************/

/*
 * Graph generator.
 *
 * Graphs of `n` vertices labeled from 0 to n-1 and `m` edges.
 * These are labeled graphs, that is, isomorphism is not taken into
 * account. VWeight is the type of vertex weights, and EWeight are the type of
 * edge weights. Generator does not generate weights. The weights are to be set
 * in the wgraph::value.
 */

template <typename VWeight, typename EWeight>
struct wgraph : gen_base<wgraph<VWeight, EWeight>> {
	int n_, m_;							  // Number of vertices and edges.
	std::set<std::pair<int, int>> edges_; // Edges that were set.
	bool is_directed_;					  // If graph is directed.
	bool has_self_loops_;				  // If self-loops are allowed.

	// Creates graph generator with `n` vertices and `m` edges.
	// Additionally, you can set if the graph is directed and if self loops are
	// allowed.
	// O(1).
	wgraph(int n, int m, bool is_directed = false, bool has_self_loops = false)
		: n_(n), m_(m), is_directed_(is_directed),
		  has_self_loops_(has_self_loops) {
		tgen_ensure(n > 0, "wgraph: n must be positive");
	}

	// Adds edge bewteen u and v (this edge must be generated).
	// O(log m).
	wgraph &add_edge(int u, int v) {
		tgen_ensure(0 <= std::min(u, v) and std::max(u, v) < n_,
					"wgraph: vertices must be indexed in [0, n)");

		if (!is_directed_ and u > v)
			std::swap(u, v);
		edges_.emplace(u, v);
		tgen_ensure(static_cast<int>(edges_.size()) <= m_,
					"wgraph: too many edges were added");
		return *this;
	}

	// Graph value.
	//
	// If not directed, in the edge list only stores edges i -> j such that
	// i < j.
	struct value : gen_value_base<value> {
		int n_, m_;						 // Number of vertices and edges.
		std::vector<std::set<int>> adj_; // Adjacency list.
		std::vector<std::pair<int, int>> edges_; // Edge list.
		bool is_directed_;						 // If graph is directed.
		bool add_1_;	// If should add 1 for printing vertex ids.
		bool print_nm_; // If should print n and m.
		std::optional<std::vector<VWeight>> vertex_weights_; // Vertex weights.
		std::optional<std::vector<EWeight>>
			edge_weights_; // Edge weights (in same order as edges_ ).

		// Creates value from `n`, `m`, and adjacecy list. The edges are
		// considered to be directed.
		// O(n + m).
		value(int n, const std::vector<std::set<int>> &adj,
			  bool is_directed = false)
			: n_(n), m_(0), adj_(adj), is_directed_(is_directed), add_1_(false),
			  print_nm_(false) {
			tgen_ensure(static_cast<int>(adj.size()) == n,
						"wgraph: value: size of adjacency list should ne `n`");

			for (int u = 0; u < n; ++u)
				for (auto v : adj[u]) {
					tgen_ensure(
						0 <= v and v < n,
						"wgraph: value: vertices must be indexed in [0, n)");
					// Undirected adjacency is symmetric: count each edge once
					// (canonical u <= v). Directed: every out-edge appears
					// once.
					if (is_directed_ or u <= v) {
						edges_.emplace_back(u, v);
						++m_;
					}
				}
		}

		// Creates value from `n`, `m`, and edge list. The edges are
		// considered to be directed.
		// O(n + m log n).
		value(int n, const std::vector<std::pair<int, int>> &edges = {},
			  bool is_directed = false)
			: n_(n), m_(edges.size()), adj_(n_), edges_(edges),
			  is_directed_(is_directed), add_1_(false), print_nm_(false) {
			for (auto [u, v] : edges) {
				tgen_ensure(
					0 <= std::min(u, v) and std::max(u, v) < n,
					"wgraph: value: vertices must be indexed in [0, n)");
				adj_[u].insert(v);
				if (!is_directed_)
					adj_[v].insert(u);
			}
		}
		value(int n, const std::set<std::pair<int, int>> &edges,
			  bool is_directed = false)
			: value(
				  n,
				  std::vector<std::pair<int, int>>(edges.begin(), edges.end()),
				  is_directed) {}

		// Weight type converstion.
		// O(n + m).
		template <typename NewVWeight, typename NewEWeight>
		typename wgraph<NewVWeight, NewEWeight>::value
		convert_weight_types() const {
			tgen_ensure(!vertex_weights_.has_value() and
							!edge_weights_.has_value(),
						"wgraph: value: cannot convert weight type after "
						"assigning weights");

			typename wgraph<NewVWeight, NewEWeight>::value new_graph(
				n_, adj_, is_directed_);
			new_graph.is_directed_ = is_directed_;
			new_graph.add_1_ = add_1_;
			new_graph.print_nm_ = print_nm_;
			return new_graph;
		}

		// Fetches number of vertices.
		int n() const { return n_; }

		// Fetches number of edges.
		int m() const { return m_; }

		// Fetches if graph is directed;
		bool is_directed() const { return is_directed_; }

		// Fetches a const ref. to adjacency list.
		const std::vector<std::set<int>> &adj() const { return adj_; }

		// Fetches a const ref. to edge set.
		const std::vector<std::pair<int, int>> &edges() const { return edges_; }

		// Fetches vertex weights.
		const std::optional<std::vector<VWeight>> &vertex_weights() const {
			return vertex_weights_;
		}

		// Fetches edge weights.
		const std::optional<std::vector<EWeight>> &edge_weights() const {
			return edge_weights_;
		}

		// Sets vertex weights.
		// O(n + m).
		template <typename NewVWeight = VWeight>
		typename wgraph<NewVWeight, EWeight>::value set_vertex_weights(
			const std::vector<NewVWeight> &vertex_weights) const {
			tgen_ensure(static_cast<int>(vertex_weights.size()) == n(),
						"wgraph: value: must give `n` vertex weights");

			auto new_graph = convert_weight_types<NewVWeight, EWeight>();
			new_graph.vertex_weights_ = vertex_weights;
			return new_graph;
		}

		// Sets edge weights.
		// O(n + m).
		template <typename NewEWeight = EWeight>
		typename wgraph<VWeight, NewEWeight>::value
		set_edge_weights(const std::vector<NewEWeight> &edge_weights) const {
			tgen_ensure(static_cast<int>(edge_weights.size()) == m(),
						"wgraph: value: must give `m` edge weights");

			auto new_graph = convert_weight_types<VWeight, NewEWeight>();
			new_graph.edge_weights_ = edge_weights;
			return new_graph;
		}

		// Adds 1 to vertex ids, for printing.
		// O(1).
		value &add_1() {
			add_1_ = true;
			return *this;
		}

		// Prints `n m` on a new line before printing the edges.
		// O(1).
		value &print_nm() {
			print_nm_ = true;
			return *this;
		}

		// Shuffles the graph's vertex labels (except those in `indices`,
		// which keep their current label) and edge order. The change is
		// applied eagerly to the underlying adjacency list, edge list,
		// vertex weights and edge weights.
		// O(n + m).
		value &shuffle_except(std::set<int> indices) {
			// Builds the relabeling: for each vertex `i`, `new_label[i]` is
			// its new id. Vertices in `indices` keep their label; the others
			// are permuted among themselves.
			std::vector<int> new_label(n());
			std::vector<int> shuffled;
			for (int i = 0; i < n(); ++i) {
				if (indices.count(i))
					new_label[i] = i;
				else
					shuffled.push_back(i);
			}
			std::vector<int> targets = shuffled;
			tgen::shuffle(targets.begin(), targets.end());
			for (size_t k = 0; k < shuffled.size(); ++k)
				new_label[shuffled[k]] = targets[k];

			// Rewrites adjacency list with new labels.
			std::vector<std::set<int>> new_adj(n());
			for (int u = 0; u < n(); ++u)
				for (int v : adj_[u])
					new_adj[new_label[u]].insert(new_label[v]);
			adj_ = new_adj;

			// Rewrites edges with new labels (canonical undirected order).
			for (auto &[u, v] : edges_) {
				u = new_label[u];
				v = new_label[v];
				if (!is_directed_ and u > v)
					std::swap(u, v);
			}

			// Permutes vertex weights to match the new labels.
			if (vertex_weights_.has_value()) {
				std::vector<VWeight> new_vw(n());
				for (int i = 0; i < n(); ++i)
					new_vw[new_label[i]] = (*vertex_weights_)[i];
				vertex_weights_ = new_vw;
			}

			// Shuffles edge order, keeping edge weights aligned.

			std::vector<int> perm(edges_.size());
			std::iota(perm.begin(), perm.end(), 0);
			tgen::shuffle(perm.begin(), perm.end());

			std::vector<std::pair<int, int>> new_edges;
			std::optional<std::vector<EWeight>> new_ew;
			if (edge_weights_.has_value())
				new_ew = std::vector<EWeight>();
			for (int i : perm) {
				new_edges.push_back(edges_[i]);
				if (new_ew.has_value())
					new_ew->push_back((*edge_weights_)[i]);
			}

			edges_ = new_edges;
			if (new_ew.has_value())
				edge_weights_ = new_ew;

			return *this;
		}

		// Shuffles the graph's vertices and edge order.
		// O(n + m).
		value &shuffle() { return shuffle_except({}); }

		// Adds `k` vertices to the graph (labeled n, n+1, ...n+k-1). Updates
		// `n` accordingly.
		// O(k) amortized.
		value &add_vertices(int k, std::optional<std::vector<VWeight>>
									   new_vertex_weights = std::nullopt) {
			n_ += k;
			adj_.resize(n());
			if (new_vertex_weights.has_value()) {
				tgen_ensure(vertex_weights().has_value(),
							"wgraph: value: cannot add weighted vertices to "
							"vertex-unweighted graph");
				tgen_ensure(
					static_cast<int>(new_vertex_weights->size()) == k,
					"wgraph: value: number of vertex weights must be equal "
					"to number of added vertices");

				vertex_weights_->insert(vertex_weights_->end(),
										new_vertex_weights->begin(),
										new_vertex_weights->end());
			} else
				tgen_ensure(!vertex_weights().has_value(),
							"wgraph: value: cannot add unweighted vertices to "
							"vertex-weighted graph");

			return *this;
		}

		// Adds edge (u, v).
		// Updates `m` accordingly.
		// O(log n) amortized.
		value &add_edge(int u, int v, std::optional<EWeight> w = std::nullopt) {
			tgen_ensure(0 <= std::min(u, v) and std::max(u, v) < n(),
						"wgraph: value: vertex ids must be valid");

			if (!is_directed() and u > v)
				std::swap(u, v);

			if (adj_[u].count(v))
				return *this;

			adj_[u].insert(v);
			if (!is_directed())
				adj_[v].insert(u);
			edges_.emplace_back(u, v);
			++m_;

			if (w.has_value()) {
				tgen_ensure(edge_weights().has_value(),
							"wgraph: value: cannot add weighted edge to "
							"edge-unweighted graph");

				edge_weights_->push_back(*w);
			} else
				tgen_ensure(!edge_weights().has_value(),
							"wgraph: value: cannot add unweighted edge to "
							"edge-weighted graph");

			return *this;
		}

		// Links graph with another `rhs`, adding the edge between u (in left
		// graph) and v (in right graph). Ids for added vertices are updated
		// accordingly.
		// O(rhs.n + rhs.m * log n) amortized.
		value &link(const value &rhs, int new_u, int new_v,
					std::optional<EWeight> new_w = std::nullopt) {
			tgen_ensure(0 <= new_u and new_u < n() and 0 <= new_v and
							new_v < rhs.n(),
						"wgraph: value: vertex ids must be valid");

			// Edges from right-hand side.
			int shift = n();
			add_vertices(rhs.n(), rhs.vertex_weights());
			for (int i = 0; i < rhs.m(); ++i) {
				auto [u, v] = rhs.edges()[i];
				add_edge(shift + u, shift + v,
						 rhs.edge_weights().has_value()
							 ? std::optional<EWeight>((*rhs.edge_weights())[i])
							 : std::nullopt);
			}

			// New edge.
			add_edge(new_u, shift + new_v, new_w);

			return *this;
		}

		// Glues the graph with another `rhs` such that index_pairs[i].first is
		// considered to be the same as index_pairs[i].second. Ids for added
		// vertices are updated accordingly.
		// O(rhs.n + rhs.m * log n) amortized.
		value &glue(const value &rhs,
					std::set<std::pair<int, int>> index_pairs) {
			// Checks validity of indices.
			std::set<int> idx_left, idx_right;
			std::vector<int> right_id_to_left(rhs.n(), -1);
			for (auto [l, r] : index_pairs) {
				tgen_ensure(
					0 <= l and l < n() and 0 <= r and r < rhs.n(),
					"wgraph: value: vertex indices to glue must be valid");
				tgen_ensure(idx_left.count(l) == 0 and idx_right.count(r) == 0,
							"wgraph: value: must not have repeated indices "
							"on the same side to glue");

				idx_left.insert(l);
				idx_right.insert(r);
				right_id_to_left[r] = l;
			}

			// Computes new ids of right vertices.
			std::vector<int> new_right_id(rhs.n(), -1);
			int intersection_lt = 0;
			std::optional<std::vector<VWeight>> rhs_vertex_weights;
			for (int i = 0; i < rhs.n(); ++i) {
				if (right_id_to_left[i] != -1) {
					// Is in intersecion.
					++intersection_lt;
					new_right_id[i] = right_id_to_left[i];
				} else {
					// New id.
					new_right_id[i] = n() + i - intersection_lt;
					if (rhs.vertex_weights().has_value()) {
						if (!rhs_vertex_weights.has_value())
							rhs_vertex_weights = std::vector<VWeight>();
						rhs_vertex_weights->push_back(
							(*rhs.vertex_weights())[i]);
					}
				}
			}

			// Adds new vertices and edges.
			add_vertices(rhs.n() - intersection_lt, rhs_vertex_weights);
			for (int i = 0; i < rhs.m(); ++i) {
				auto [u, v] = rhs.edges()[i];
				add_edge(new_right_id[u], new_right_id[v],
						 rhs.edge_weights().has_value()
							 ? std::optional<EWeight>((*rhs.edge_weights())[i])
							 : std::nullopt);
			}

			return *this;
		}
		value &glue(const value &rhs,
					std::initializer_list<std::pair<int, int>> il) {
			return glue(rhs, std::set<std::pair<int, int>>(il));
		}

		// Glues the graph with another `rhs` at `indices`. That is, idx in
		// `indices` are considered to be the same vertex. Ids for added
		// vertices are updated accordingly.
		// O(rhs.n + rhs.m * log n) amortized.
		value &glue(const value &rhs, std::set<int> indices) {
			std::set<std::pair<int, int>> index_pairs;
			for (auto i : indices)
				index_pairs.emplace(i, i);
			return glue(rhs, index_pairs);
		}
		value &glue(const value &rhs, const std::initializer_list<int> &il) {
			return glue(rhs, std::set<int>(il));
		}

		// Computes uniformly random subgraph of graph with num_edges edges.
		// O(m) amortized.
		value &random_subgraph(int num_edges) {
			tgen_ensure(
				num_edges <= m(),
				"wgraph: value: can choose at most `m` edges from graph");

			std::vector<std::pair<int, int>> new_edges;
			std::optional<std::vector<EWeight>> new_edge_weights;

			int left = m();
			for (int i = 0; i < m(); ++i) {
				if (next(1, left--) <= num_edges) {
					new_edges.push_back(edges()[i]);
					if (edge_weights_.has_value()) {
						if (!new_edge_weights.has_value())
							new_edge_weights = std::vector<EWeight>();
						new_edge_weights->push_back((*edge_weights())[i]);
					}
					--num_edges;
				}
			}

			edges_ = new_edges;
			edge_weights_ = new_edge_weights;
			return *this;
		}

		// Computes a random (not uniform) connected subgraph with `num_edges`
		// edges.
		// 1. Picks a spanning tree via randomized Prim.
		// 2. Adds additional edges uniformly at random.
		// O(n + m).
		value &random_connected_subgraph(int num_edges) {
			tgen_ensure(!is_directed_,
						"wgraph: value: random_connected_subgraph is only for "
						"undirected graphs");
			tgen_ensure(num_edges >= n() - 1,
						"wgraph: value: random_connected_subgraph needs at "
						"least `n - 1` edges");
			tgen_ensure(
				num_edges <= m(),
				"wgraph: value: can choose at most `m` edges from graph");

			// Builds an incidence list: for each vertex, the (neighbor, edge
			// index) pairs.
			std::vector<std::vector<std::pair<int, int>>> incident(n());
			for (int i = 0; i < m(); ++i) {
				auto [u, v] = edges_[i];
				incident[u].emplace_back(v, i);
				incident[v].emplace_back(u, i);
			}

			// Randomized Prim.
			std::vector<bool> vis(n(), false);
			std::vector<int> queue;
			std::vector<bool> in_tree(m(), false);
			int tree_count = 0;

			int start = tgen::next<int>(0, n() - 1);
			vis[start] = true;
			queue.push_back(start);

			while (!queue.empty()) {
				int i = tgen::next<int>(0, queue.size() - 1);
				int u = queue[i];
				std::swap(queue[i], queue.back());
				queue.pop_back();

				for (auto [v, edge_idx] : incident[u]) {
					if (!vis[v]) {
						vis[v] = true;
						queue.push_back(v);
						in_tree[edge_idx] = true;
						++tree_count;
					}
				}
			}
			tgen_ensure(tree_count == n() - 1,
						"wgraph: value: random_connected_subgraph requires the "
						"current graph to be connected");

			// Splits edge indices into tree edges and the rest.
			std::vector<int> tree_idx, rest_idx;
			for (int i = 0; i < m(); ++i) {
				if (in_tree[i])
					tree_idx.push_back(i);
				else
					rest_idx.push_back(i);
			}

			tgen::shuffle(rest_idx.begin(), rest_idx.end());

			std::vector<int> chosen_idx;
			chosen_idx.insert(chosen_idx.end(), tree_idx.begin(),
							  tree_idx.end());
			chosen_idx.insert(chosen_idx.end(), rest_idx.begin(),
							  rest_idx.begin() + num_edges - (n() - 1));
			detail::tgen_ensure_against_bug(
				chosen_idx.size() == num_edges,
				"wgraph: value: chose a wrong number of edges");

			std::vector<std::pair<int, int>> new_edges;
			std::optional<std::vector<EWeight>> new_edge_weights;
			if (edge_weights_.has_value())
				new_edge_weights = std::vector<EWeight>();
			for (int i : chosen_idx) {
				new_edges.push_back(edges_[i]);
				if (new_edge_weights.has_value())
					new_edge_weights->push_back((*edge_weights_)[i]);
			}

			edges_ = new_edges;
			edge_weights_ = new_edge_weights;
			m_ = num_edges;
			return *this;
		}

		// Self loops are mainteind for complement.
		// O(n^2).
		value &operator!() {
			tgen_ensure(!edge_weights_.has_value(),
						"wgraph: value: cannot compute complement of "
						"edge-weighted graph");

			m_ = 0;
			std::vector<std::pair<int, int>> compl_edges;
			for (int i = 0; i < n_; ++i) {
				std::set<int> complement;
				for (int j = 0; j < n_; ++j) {
					bool add_j = false;
					if (j == i and adj_[i].count(j))
						add_j = true;
					if (j != i and !adj_[i].count(j))
						add_j = true;

					if (add_j) {
						complement.insert(j);
						// If i > j and !is_directed(), we don't add the edge.
						if (i <= j or is_directed()) {
							compl_edges.emplace_back(i, j);
							++m_;
						}
					}
				}
				std::swap(adj_[i], complement);
			}
			std::swap(edges_, compl_edges);

			return *this;
		}

		// Concatenates two values.
		// O(N + M log N), N = n + rhs.n, M = m + rhs.m.
		value operator+(const value &rhs) const {
			tgen_ensure(is_directed() == rhs.is_directed(),
						"wgraph: value: concatened graphs must have the same "
						"is_directed value");

			std::vector<std::pair<int, int>> edges = edges_;
			for (auto [u, v] : rhs.edges())
				edges.emplace_back(n() + u, n() + v);

			value concat(n() + rhs.n(), edges, is_directed());
			if (rhs.add_1_)
				concat.add_1();
			if (rhs.print_nm_)
				concat.print_nm();

			// Merge vertex weights.
			tgen_ensure(vertex_weights().has_value() ==
							rhs.vertex_weights().has_value(),
						"wgraph: value: cannot concatenate vertex-weighted "
						"wgraph to unweighted");
			if (vertex_weights().has_value()) {
				concat.set_vertex_weights(*vertex_weights());
				concat.vertex_weights_->insert(concat.vertex_weights_->end(),
											   rhs.vertex_weights()->begin(),
											   rhs.vertex_weights()->end());
			}

			// Merge edge weights.
			tgen_ensure(edge_weights().has_value() ==
							rhs.edge_weights().has_value(),
						"wgraph: value: cannot concatenate edge-weighted "
						"wgraph to unweighted");
			if (edge_weights().has_value()) {
				concat.set_edge_weights(*edge_weights());
				concat.edge_weights_->insert(concat.edge_weights_->end(),
											 rhs.edge_weights()->begin(),
											 rhs.edge_weights()->end());
			}

			return concat;
		}

		// Prints to std::ostream.
		// O(n + m).
		friend std::ostream &operator<<(std::ostream &out, const value &val) {
			// Prints `n` and `m`.
			if (val.print_nm_)
				out << val.n() << " " << val.m() << std::endl;

			// Prints vertex weights.
			if (val.vertex_weights()) {
				for (int i = 0; i < val.n(); ++i) {
					if (i > 0)
						out << " ";
					out << (*val.vertex_weights())[i];
				}
				out << std::endl;
			}

			// Prints edges.
			for (int i = 0; i < val.m(); ++i) {
				auto [u, v] = val.edges()[i];
				out << (u + val.add_1_) << " " << (v + val.add_1_);

				// Edge weight.
				if (val.edge_weights().has_value())
					out << " " << (*val.edge_weights())[i];

				out << std::endl;
			}

			return out;
		}

		// Gets a std::tuple<n, m, adj> representing the value.
		std::tuple<int, int, std::vector<std::set<int>>> to_std() const {
			return std::tuple(n_, m_, adj_);
		}
	};

	// Generates graph value.
	// O(n + m log n).
	value gen() const {
		value new_graph(
			n_, std::vector<std::pair<int, int>>(edges_.begin(), edges_.end()),
			is_directed_);

		detail::tgen_ensure_against_bug(new_graph.m() <= m_,
										"wgraph: too many edges were added");

		tgen::pair gen_repeat(0, n_ - 1);
		if (has_self_loops_) {
			if (!is_directed_)
				gen_repeat.leq();
		} else {
			if (is_directed_)
				gen_repeat.neq();
			else
				gen_repeat.lt();
		}
		auto edge_gen = gen_repeat.distinct();

		while (new_graph.m() < m_) {
			pair<int>::value new_edge_pair(0, 0);
			try {
				new_edge_pair = edge_gen.gen();
			} catch (std::runtime_error &e) {
				if (std::string(e.what()) ==
					"tgen: distinct: no more distinct values")
					throw detail::error("wgraph: not enough edges to generate");
				throw e;
			}

			new_graph.add_edge(new_edge_pair.first(), new_edge_pair.second());
		}

		return new_graph;
	}

	// Gets a (not uniformly) random connected undirected graph.
	// 1. Preset edges induce a spanning forest on their components.
	// 2. Then, uniformly random edges between components are added.
	// 3. Remaining edges are added uniformly at random.
	// O(n + m log n).
	value get_connected() const {
		tgen_ensure(!is_directed_,
					"wgraph: get_connected is only for undirected graphs");
		tgen_ensure(m_ >= n_ - 1,
					"wgraph: connected graph needs at least n - 1 edges");

		// Computes connected components.

		std::vector<std::set<int>> adj(n_);
		for (auto [u, v] : edges_) {
			adj[u].insert(v);
			adj[v].insert(u);
		}

		std::vector<int> comp_size;
		std::vector<std::vector<int>> component_ids;
		std::vector<bool> vis(n_, false);
		std::queue<int> q;

		for (int i = 0; i < n_; ++i) {
			if (vis[i])
				continue;

			vis[i] = true;
			q.push(i);
			comp_size.push_back(0);
			component_ids.emplace_back();
			while (q.size()) {
				int u = q.front();
				q.pop();
				++comp_size.back();
				component_ids.back().push_back(u);
				for (int v : adj[u]) {
					if (!vis[v]) {
						vis[v] = true;
						q.push(v);
					}
				}
			}
		}

		auto connected_graph = *this;

		// Adds edges between connected components.
		if (component_ids.size() > 1) {
			std::vector<int> prufer_values =
				many_by_distribution(component_ids.size() - 2, comp_size);
			for (auto [u, v] : detail::edges_from_prufer(prufer_values))
				connected_graph.add_edge(pick(component_ids[u]),
										 pick(component_ids[v]));
		}

		// Generates remaining edges.
		return connected_graph.gen();
	}

	// Gets a (not uniformly) random directed acyclic graph.
	// 1. Randomized Kahn (uniform choice among indegree-0 vertices) yields a
	//    random topological order of the preset edges (which must be acyclic).
	// 2. Extra edges are sampled randomly using the order.
	// O(n + m log n).
	value get_acyclic() const {
		tgen_ensure(is_directed_,
					"wgraph: get_acyclic is only for directed graphs");

		std::vector<std::vector<int>> adj(n_);
		std::vector<int> indeg(n_, 0);
		for (auto [u, v] : edges_) {
			adj[u].push_back(v);
			++indeg[v];
		}

		std::vector<int> available;
		for (int i = 0; i < n_; ++i)
			if (indeg[i] == 0)
				available.push_back(i);

		// Random topological order using randomized Kahn's algorithm.
		std::vector<int> order;
		while (!available.empty()) {
			int idx = next(0, static_cast<int>(available.size()) - 1);
			int u = available[idx];
			std::swap(available[idx], available.back());
			available.pop_back();

			order.push_back(u);
			for (int v : adj[u])
				if (--indeg[v] == 0)
					available.push_back(v);
		}

		tgen_ensure(static_cast<int>(order.size()) == n_,
					"wgraph: preset edges contain a directed cycle");

		value new_graph(n_, edges_, true);

		// Generates final edges.

		detail::tgen_ensure_against_bug(new_graph.m() <= m_,
										"wgraph: too many edges were added");

		if (new_graph.m() < m_) {
			auto edge_gen = tgen::pair(0, n_ - 1).lt().distinct();

			while (new_graph.m() < m_) {
				pair<int>::value idx_pair(0, 0);
				try {
					idx_pair = edge_gen.gen();
				} catch (std::runtime_error &e) {
					if (std::string(e.what()) ==
						"tgen: distinct: no more distinct values")
						throw detail::error(
							"wgraph: not enough edges to generate");
					throw e;
				}

				new_graph.add_edge(order[idx_pair.first()],
								   order[idx_pair.second()]);
			}
		}

		return new_graph;
	}

	// Skewed undirected connected graph.
	// 1. Builds the same skewed labeled tree as wtree::get_skewed(elongation)
	//    (root 0, parent(i) = wnext(i, elongation) for i >= 1).
	// 2. Adds the remaining edges: pick an endpoint u uniformly;
	//    pick k uniformly in [1, spread]; walk from u toward the root k
	//    times along tree parents to get v; add edge (u, v).
	// Preset edges are not supported.
	// If elongation is small, generates a graph with small diameter.
	// If elongation is large, generates a graph with large diameter, with
	// vertices 0 and n-1 being far apart.
	// O(n + m log^2 n).
	value get_skewed(int elongation, int spread) const {
		tgen_ensure(!is_directed_,
					"wgraph: get_skewed is only for undirected graphs");
		tgen_ensure(!has_self_loops_,
					"wgraph: get_skewed does not support self-loops");
		tgen_ensure(edges_.empty(),
					"wgraph: get_skewed does not support preset edges");
		tgen_ensure(
			m_ >= n_ - 1,
			"wgraph: skewed graph needs at least n - 1 edges to be connected");
		tgen_ensure(spread >= 1,
					"wgraph: get_skewed spread must be at least 1");

		value new_graph(n_);

		std::vector<int> parent(n_), depth(n_, 0);
		parent[0] = 0;
		for (int i = 1; i < n_; ++i) {
			int p = wnext<int>(i, elongation);
			parent[i] = p;
			depth[i] = depth[p] + 1;
			new_graph.add_edge(i, p);
		}

		// Binary lifting.

		int lg = 1;
		while ((1 << lg) <= n_)
			++lg;

		std::vector<std::vector<int>> up(lg, std::vector<int>(n_));
		for (int v = 0; v < n_; ++v)
			up[0][v] = parent[v];
		for (int j = 1; j < lg; ++j)
			for (int v = 0; v < n_; ++v)
				up[j][v] = up[j - 1][up[j - 1][v]];

		// O(log k).
		auto kth_parent = [&](int u, int k) {
			for (int j = 0; j < lg; ++j)
				if (k >> j & 1)
					u = up[j][u];
			return u;
		};

		// Creates uniform generator of edges (u, v) such that v is ancestor of
		// u. For that, every u has depth[u] choices for v, so we weight u by
		// depth[u]. After that we can just pick the ancestor uniformly.
		weighted_sampler vertex_choice(depth);
		distinct extra_edges([&]() -> std::pair<int, int> {
			int u = vertex_choice.next();
			int k = next(1, spread);
			return {u, kth_parent(u, k)};
		});

		// Adds the remaining edges.
		while (new_graph.m() < m_) {
			std::pair<int, int> edge;
			try {
				edge = extra_edges.gen();
			} catch (const std::runtime_error &e) {
				if (std::string(e.what()) ==
					"tgen: distinct: no more distinct values")
					throw detail::error("wgraph: not enough edges to generate");
				throw e;
			}

			new_graph.add_edge(edge.first, edge.second);
		}

		return new_graph;
	}
};

/*
 * Other types of weighted-ness.
 */

// Vertex weighted graph.
template <typename VWeight> using vgraph = wgraph<VWeight, int>;

// Edge weighted graph.
template <typename EWeight> using egraph = wgraph<int, EWeight>;

// Unweighted graph.
struct graph : wgraph<int, int> {
	using wgraph::wgraph;

	// Uniformly random bipartite graph. The first side has vertices 0 .. n1-1,
	// the second n1 .. n1+n2-1.
	// O(n1 + n2 + m log n).
	static graph::value gen_bipartite(int n1, int n2, int m) {
		tgen_ensure(m <= static_cast<long long>(n1) * n2,
					"graph: bipartite graph has at most n1 * n2 edges");

		graph bipartite(n1 + n2, m);
		for (auto [u, v] :
			 pair<int>(0, n1 - 1, n1, n1 + n2 - 1).gen_list(m).to_std())
			bipartite.add_edge(u, v);
		return bipartite.gen();
	}
};

/*
 * Standard graphs.
 */

// Complete.
// O(n^2).
inline graph::value K(int n) { return graph(n, n * (n - 1) / 2).gen(); }

// Path.
// Path with `n`vertices. The edges of the path are 0 and n-1.
// O(n).
inline graph::value P(int n) {
	graph g(n, n - 1);
	for (int i = 0; i + 1 < n; ++i)
		g.add_edge(i, i + 1);
	return g.gen();
}

// Cycle.
// n >= 3.
// O(n).
inline graph::value C(int n) {
	tgen_ensure(n >= 3, "graph: cycle size must be at least 3");

	graph g(n, n);
	for (int i = 0; i < n; ++i)
		g.add_edge(i, (i + 1) % n);
	return g.gen();
}

// Complete bipartite.
// The first side has vertices `0` to `n1-1`, the second side has vertices `n1`
// to `n1+n2-1`.
// O(n1 * n2).
inline graph::value K(int n1, int n2) {
	graph g(n1 + n2, static_cast<long long>(n1) * n2);
	for (int i = 0; i < n1; ++i)
		for (int j = 0; j < n2; ++j)
			g.add_edge(i, n1 + j);
	return g.gen();
}

// Star.
// The center is vertex 0.
// O(n).
inline graph::value S(int n) { return K(1, n - 1); }

/************
 *          *
 *   HACK   *
 *          *
 ************/

namespace hack {

namespace detail {

using namespace tgen::detail;

// Computes polynomial hash of a string.
// O(|s|).
inline int hash_string(const std::string &s, int base, int mod) {
	long long h = 0;
	for (char c : s)
		h = (h * base + c - 'a' + 1) % mod;
	return h;
}

// Estimates the length of the string to very likely have a collision.
inline int estimate_length(int alphabet_size, int mod) {
	// Magic constants.
	double base_len = 2.5 * std::log(std::sqrt(static_cast<double>(mod)));
	double scale = std::log(static_cast<double>(alphabet_size)) / std::log(2.0);
	double adjusted = base_len / std::max(1.0, scale * 0.7);

	return static_cast<int>(std::ceil(adjusted));
}

// Collides two strings to have the same polynomial hash.
// O(sqrt(mod) log(mod)) with high probability.
inline std::pair<std::string, std::string>
birthday_attack(const std::vector<std::string> &alphabet, int base, int mod) {
	tgen_ensure(0 < base and base < mod,
				"birthday_attack: base must be in (0, mod)");
	std::map<uint64_t, std::vector<int>> seen;
	int length = estimate_length(alphabet.size(), mod);

	while (true) {
		std::vector<int> seq(length);

		std::string s;
		s.reserve(length * alphabet[0].size());

		for (int i = 0; i < length; ++i) {
			seq[i] = next<int>(0, alphabet.size() - 1);
			s += alphabet[seq[i]];
		}

		int h = hash_string(s, base, mod);

		auto it = seen.find(h);
		if (it != seen.end() and it->second != seq) {
			std::string a, b;

			for (int x : it->second)
				a += alphabet[x];
			for (int x : seq)
				b += alphabet[x];

			if (a != b)
				return {a, b};
		}

		seen[h] = seq;
	}
}

// Tried to find correct multipliers for unordered_map/set to force
// collisions. O(1).
inline std::set<long long> std_hash_multipliers() {
	std::set<long long> multipliers = {85229};

	// Codeforces GCC GNU G++17 7.3.0 case.
	bool codeforces_gcc_case = true;
	if (cpp.version_ != 0 and cpp.version_ != 17)
		codeforces_gcc_case = false;
	if (compiler.kind_ != compiler_kind::unknown and
		compiler.kind_ != compiler_kind::gcc)
		codeforces_gcc_case = false;
	if (compiler.major_ > 7)
		codeforces_gcc_case = false;

	if (codeforces_gcc_case)
		multipliers.insert(107897);

	return multipliers;
}

} // namespace detail

// Fetches prefix of length n of the string "abacabadabacabae...".
// O(n).
inline std::string abacaba(int n) {
	tgen_ensure(n > 0, "str: size must be positive");
	std::string str = "a";
	char c = 'a';
	while (static_cast<int>(str.size()) < n) {
		int prev_size = str.size();
		str += ++c;
		for (int j = 0; j < prev_size and static_cast<int>(str.size()) < n; ++j)
			str += str[j];
	}
	return str;
}

// Two strings that have same polynomial hash for any base, for
// mod = power of 2 up to 2^64.
// Thue–Morse.
// O(1).
inline std::pair<std::string, std::string> unsigned_polynomial_hash_hack() {
	std::string a, b;
	int size = 1 << 10;
	for (int i = 0; i < size; ++i) {
		a += 'a' + math::detail::popcount(i) % 2;
		b += 'a' + ('b' - a[i]);
	}
	return {a, b};
}

// Collides two strings to have the same polynomial hash.
// O(sqrt(mod) log(mod)) with high probability.
// 0 < base < mod.
inline std::pair<std::string, std::string>
polynomial_hash_hack(int alphabet_size, int base, int mod) {
	tgen_ensure(alphabet_size > 1, "str: alphabet size must be greater than 1");
	tgen_ensure(0 < base and base < mod, "str: base must be in (0, mod)");

	std::vector<std::string> alphabet(alphabet_size);
	for (int i = 0; i < alphabet_size; ++i)
		alphabet[i] = std::string(1, 'a' + i);
	std::iota(alphabet.begin(), alphabet.end(), 'a');
	return detail::birthday_attack(alphabet, base, mod);
}

// Collides two strings to have the same polynomial hash for multiple bases
// and mods (up to 2 pairs).
// O(sqrt(mod) log^2 (mod)) with high probability,
// with mod = max(mod_1, mod_2).
inline std::pair<std::string, std::string>
polynomial_hash_hack(int alphabet_size, std::vector<int> bases,
					 std::vector<int> mods) {
	tgen_ensure(bases.size() == mods.size(),
				"str: bases and mods must have the same size");
	tgen_ensure(bases.size() > 0,
				"str: must have at least one (base, mod) pair");
	tgen_ensure(bases.size() <= 2, "str: multi-hash hack only supported "
								   "for up to 2 (base, mod) pairs");

	std::vector<std::string> alphabet(alphabet_size);
	for (int i = 0; i < alphabet_size; ++i)
		alphabet[i] = std::string(1, 'a' + i);
	auto [S1, T1] = detail::birthday_attack(alphabet, bases[0], mods[0]);
	if (bases.size() == 1)
		return {S1, T1};
	return detail::birthday_attack({S1, T1}, bases[1], mods[1]);
}

// Returns a list of integers for unordered_map/set to force collisions.
// O(size).
inline std::vector<long long> std_unordered(int size) {
	tgen_ensure(size > 0, "misc: unordered_hack: size must be positive");
	std::set<long long> multipliers = detail::std_hash_multipliers();
	long long mult = 1;
	std::set<long long>::iterator it = multipliers.begin();

	std::vector<long long> list;
	while (static_cast<int>(list.size()) < size) {
		list.push_back(mult * (*it));
		++it;
		if (it == multipliers.end()) {
			it = multipliers.begin();
			++mult;
		}
	}
	return list;
}

// Returns queries that force \Theta(q sqrt n) asymptotic
// for Mo algorithm for offline range queries.
// Forces \Theta(q sqrt n) pointer moves for any ordering.
// O(n log n + q).
inline std::vector<std::pair<int, int>> mo(int n, int q) {
	std::set<std::pair<int, int>> queries;

	// Adversarial case.
	int sq = std::sqrt(n);
	for (int i = 0; i < sq; ++i) {
		for (int j = i; j < sq; ++j) {
			if (i * sq < n and j * sq < n)
				queries.emplace(i * sq, j * sq);
		}
	}

	// Push extra queries.
	for (int i = 0; i < n; ++i)
		if (static_cast<int>(queries.size()) < q) {
			queries.emplace(0, i);
			queries.emplace(i, i);
			queries.emplace(i, n - 1);
		}

	return choose(shuffled(queries), q);
}

// Returns list of strings that have a high cost to insert in a std::set.
// Forces cost \Theta(size log(size)).
// Generates: {b, ab, aab, aaab, ...}.
// O(size log(size)).
inline std::vector<std::string> string_set(int size) {
	std::vector<std::string> list;
	int k = 0, left = size;
	while (left > 0) {
		int cur_size = std::min(left, k + 1);
		left -= cur_size;

		char right_char = cur_size == k + 1 ? 'b' : 'c';
		list.push_back(std::string(cur_size - 1, 'a') + right_char);

		++k;
	}
	return tgen::shuffled(list);
}

} // namespace hack

/*********************
 *                   *
 *   MISCELLANEOUS   *
 *                   *
 *********************/

namespace misc {

// Generates a random balanced parentheses sequence with k '(' and k ')'.
// Valid meanst that for no prefix there are more ')' than '('.
// O(size).
inline std::string gen_parenthesis(int size) {
	tgen_ensure(size > 0 and size % 2 == 0,
				"misc: parenthesis: size must a positive even number");

	int k = size / 2;
	std::string s;
	int open = 0, close = 0;

	for (int i = 0; i < size; ++i) {
		if (open == k) {
			s += ')';
			++close;
			continue;
		}
		if (open == close) {
			s += '(';
			++open;
			continue;
		}

		long long a = k - open, b = k - close, h = open - close;

		// Probability of placing '(':
		// P('(') = (k - open) * (bal + 1) / (rem)
		// Derived from ballot numbers ratio.
		long long num = a * (h + 2);
		long long den = (a + b) * (h + 1);

		if (next<long long>(1, den) <= num) {
			s += '(';
			++open;
		} else {
			s += ')';
			++close;
		}
	}

	return s;
}

} // namespace misc

} // namespace tgen

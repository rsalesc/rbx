#include <cstdio>
#include <string>

// Minimal token-comparison checker, deliberately not testlib-based so this
// package compiles with nothing but a C++ compiler. Follows the testlib command
// line (`<checker> <input> <output> <answer>`) and exit codes (0 = accepted,
// 1 = wrong answer).
static bool read_all(const char* path, std::string& out) {
    FILE* f = fopen(path, "r");
    if (f == nullptr) {
        return false;
    }
    char buf[4096];
    while (fgets(buf, sizeof(buf), f) != nullptr) {
        out += buf;
    }
    fclose(f);
    return true;
}

static std::string tokens(const std::string& text) {
    std::string res;
    bool in_space = true;
    for (char c : text) {
        if (isspace(static_cast<unsigned char>(c))) {
            in_space = true;
            continue;
        }
        if (!in_space) {
            res += c;
            continue;
        }
        if (!res.empty()) {
            res += ' ';
        }
        res += c;
        in_space = false;
    }
    return res;
}

int main(int argc, char* argv[]) {
    if (argc != 4) {
        return 3;
    }
    std::string output;
    std::string answer;
    if (!read_all(argv[2], output) || !read_all(argv[3], answer)) {
        return 3;
    }
    if (tokens(output) != tokens(answer)) {
        fprintf(stderr, "wrong answer\n");
        return 1;
    }
    return 0;
}

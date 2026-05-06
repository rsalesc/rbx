#include <cstdio>
#include <cstdlib>

// Minimal generator: takes two integers as args and prints them as the input.
// Usage: gen <a> <b>
int main(int argc, char* argv[]) {
    if (argc != 3) {
        return 1;
    }
    int a = atoi(argv[1]);
    int b = atoi(argv[2]);
    printf("%d %d\n", a, b);
    return 0;
}

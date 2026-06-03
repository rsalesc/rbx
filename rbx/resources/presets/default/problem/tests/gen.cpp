#include "testlib.h"
// Reference random generator. Docs: https://rsalesc.github.io/rbx/setters/testset/
// First positional argument is the max value for A and B (the RNG is seeded
// from the whole argv, so different arguments also give different tests).

using namespace std;

int main(int argc, char *argv[]) {
    registerGen(argc, argv, 1);

    println(rnd.next(1, opt<int>(1)), rnd.next(1, opt<int>(1)));
}

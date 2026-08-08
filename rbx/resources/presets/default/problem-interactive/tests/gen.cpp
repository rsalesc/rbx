#include "testlib.h"
// A testlib generator. Docs: https://rsalesc.github.io/rbx/setters/testset/
//
// Prints a test in the format read by the interactor: the size of the search
// range N, followed by the secret number S.

using namespace std;

int main(int argc, char *argv[]) {
    registerGen(argc, argv, 1);

    int n = opt<int>(1);
    int s = rnd.next(1, n);
    println(n, s);
}

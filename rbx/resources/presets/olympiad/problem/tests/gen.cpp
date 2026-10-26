#include "testlib.h"
// A testlib generator. Docs: https://rsalesc.github.io/rbx/setters/testset/

using namespace std;

int main(int argc, char *argv[]) {
    registerGen(argc, argv, 1);

    int a = rnd.next(1, opt<int>(1));
    int b = rnd.next(1, opt<int>(1));
    println(a, b);
}

#include "testlib.h"

using namespace std;

int main(int argc, char *argv[]) {
    registerGen(argc, argv, 1);

    println(rnd.next(1, opt<int>(1)), rnd.next(1, opt<int>(1)));
}
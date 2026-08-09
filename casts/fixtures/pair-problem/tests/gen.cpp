#include "testlib.h"

using namespace std;

// Usage: gen <N.max> [seed]
int main(int argc, char *argv[]) {
    registerGen(argc, argv, 1);
    cout << rnd.next(2, opt<int>(1)) << endl;
}

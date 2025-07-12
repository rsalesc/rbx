#include "testlib.h"

using namespace std;

int main(int argc, char *argv[]) {
    registerValidation(argc, argv);

    inf.readInt(1, 1'000'000'000, "n");
    inf.readEoln();
    inf.readEof();
}
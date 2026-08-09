#include "rbx.h"
#include "testlib.h"

// The bounds are read exactly as they would be without per-group vars: the
// validator has no idea groups exist. `getVar` resolves `AB.min` against the
// group rbx passes as `--group`, so `nonneg` sees 0 and `full` sees -200.
int main(int argc, char* argv[]) {
    registerValidation(argc, argv);

    int MIN_AB = getVar<int>("AB.min");
    int MAX_AB = getVar<int>("AB.max");

    inf.readInt(MIN_AB, MAX_AB, "A");
    inf.readSpace();
    inf.readInt(MIN_AB, MAX_AB, "B");
    inf.readEoln();
    inf.readEof();
}

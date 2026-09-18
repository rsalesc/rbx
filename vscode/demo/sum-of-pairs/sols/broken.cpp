#include <iostream>
using namespace std;

// Does not compile. Declared `ac`, because that is the case the run view exists
// to catch: a solution the setter believes in, broken mid-edit, that rbx then
// filters out of the run entirely -- it is absent from the skeleton's
// `solutions` and from `compiled_solutions`, so before the Compilation Findings
// panel it simply vanished from the sidebar with nothing saying why.
//
// `c` was never declared. Keep the typo: it is the whole point of the file.
int main() {
    long long a, b;
    cin >> a >> b;
    cout << a + c << endl;
    return 0;
}

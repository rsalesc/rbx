#include <iostream>
using namespace std;

// MISMATCH (pooled, the other direction): declared `wa`, but is correct.
//
// A solution that passes when it was supposed to fail is just as broken a
// package as one that fails when it was supposed to pass -- it means the
// testset never actually catches the bug this solution was added to
// demonstrate. Expected WRONG_ANSWER, got ACCEPTED.
int main() {
    long long a, b;
    cin >> a >> b;
    cout << a + b << endl;
    return 0;
}

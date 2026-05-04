#include "testlib.h"
#include <ctime>
#include <unistd.h>

using namespace std;

int main(int argc, char *argv[]) {
  registerGen(argc, argv, 1);
  // Intentionally NOT seeded from argv: this generator is used in tests to
  // verify the determinism check. It must produce different output on
  // back-to-back runs.
  static int nonce = 0;
  unsigned long long v =
      (unsigned long long)time(NULL) ^
      (unsigned long long)getpid() ^
      (unsigned long long)(++nonce);
  cout << v << endl;
  return 0;
}

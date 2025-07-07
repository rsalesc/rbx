#include "testlib.h"

using namespace std;

int main(int argc, char *argv[]) {
  registerGen(argc, argv, 1);
  int n = opt<int>(1);
  cout << n << endl;
  return 0;
}

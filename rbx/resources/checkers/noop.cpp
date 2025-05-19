#include "testlib.h"

using namespace std;

int main(int argc, char *argv[]) {
  setName("no-op checker");
  registerTestlibCmd(argc, argv);

  while (!ouf.seekEof()) {
    ouf.skipChar();
  }
  quitf(_ok, "ok");
}
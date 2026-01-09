#include <iostream>
#include <string>
#include <vector>

using namespace std;

int main(int argc, char *argv[]) {
  string group = "default";
  for (int i = 1; i < argc; ++i) {
    string arg = argv[i];
    if (arg == "--group" && i + 1 < argc) {
      group = argv[i + 1];
      i++;
    }
  }

  int x;
  if (!(cin >> x))
    return 1;

  int limit = 1000;
  if (group == "small")
    limit = 10;
  else if (group == "large")
    limit = 100;

  if (x > limit) {
    cerr << "Value " << x << " exceeds limit " << limit << " for group "
         << group << endl;
    return 1;
  }

  return 0;
}

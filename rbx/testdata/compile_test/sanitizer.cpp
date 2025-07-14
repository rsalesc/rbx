#include <iostream>
using namespace std;

int main() {
  int *ptr = new int(42);
  cout << *ptr << endl;
  // Memory leak - not deleting ptr
  return 0;
}
#include <iostream>
using namespace std;

int main() {
  undeclared_variable = 42; // This will cause a compilation error
  cout << "This won't compile" << endl;
  return 0;
}
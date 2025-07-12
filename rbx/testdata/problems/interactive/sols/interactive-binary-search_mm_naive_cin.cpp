#include <iostream>

using namespace std;

int main() {
  int n;
  cin >> n;
  for (int i = n; i >= 1; i--) {
    cout << i << endl << flush;
    string response;
    cin >> response;
    if (response == ">=") {
      cout << "! " << i << endl << flush;
      return 0;
    }
  }
}
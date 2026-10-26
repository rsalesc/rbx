#include <bits/stdc++.h>

using namespace std;

int32_t main() {
  int32_t n;
  cin >> n;

  // Binary search: each guess either hits the secret number or halves the
  // remaining range, so at most ceil(log2(n + 1)) guesses are needed.
  int32_t lo = 1, hi = n;
  while (true) {
    int32_t mid = lo + (hi - lo) / 2;
    // `endl` flushes; without a flush the interactor would never see the
    // guess and the solution would hang until the time limit.
    cout << mid << endl;

    string answer;
    cin >> answer;
    if (answer == "=") {
      break;
    } else if (answer == "<") {
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
}

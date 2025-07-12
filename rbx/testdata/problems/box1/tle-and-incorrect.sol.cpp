#include <bits/stdc++.h>
#include <ctime>

using namespace std;

void busy_loop() {
  double wait = 1.0;
  int start = clock();
  int end = clock();
  while (((double) (end - start)) / CLOCKS_PER_SEC < wait)
  {
    end = clock();
  }
}

int32_t main() {
    ios::sync_with_stdio(false);
    cin.tie(0);

    int n; cin >> n;
    busy_loop();

    vector<int> divisors;
    for(int i = 1; i*i <= n; i++) {
      if (n % i == 0) {
        divisors.push_back(i);
      }
    }

    sort(divisors.begin(), divisors.end());
    for (int x : divisors) cout << x << '\n';
    return 0;
}

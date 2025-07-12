#include <bits/stdc++.h>
#include <ctime>

using namespace std;

void busy_loop() {
  double wait = 5.0;
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

    cout << "hard" << endl;
    return 0;
}

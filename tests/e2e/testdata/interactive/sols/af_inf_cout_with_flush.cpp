#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <map>
#include <queue>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#define forn(i, n) for (int i = 0; i < n; ++i)
#define fore(i, l, r) for (int i = int(l); i <= int(r); ++i)
#define sz(v) int(v.size())
#define all(v) v.begin(), v.end()
#define pb push_back
#define mp make_pair
#define x first
#define y1 ________y1
#define y second
#define ft first
#define sc second
#define pt pair<int, int>

template <typename X> inline X abs(const X &a) { return a < 0 ? -a : a; }
template <typename X> inline X sqr(const X &a) { return a * a; }

typedef long long li;
typedef long double ld;

using namespace std;

const int INF = 1000 * 1000 * 1000;
const ld EPS = 1e-9;
const ld PI = acos(-1.0);

int n;
int lf, rg;

bool read() {
  cin >> n;
  return true;
}

void solve() {
  lf = 1, rg = n;
  int it = 0;
  while (rg - lf > 0) {
    it++;
    int mid = (lf + rg + 1) / 2;
    cout << mid << endl;
    fflush(stdout);
    string s;
    cin >> s;
    if (s == "<")
      rg = mid - 1;
    else
      lf = mid;
    if (it > 5) {
      while (true) {
        cout << rand() % n + 1 << endl;
        fflush(stdout);
      }
    }
  }
  cout << "! " << lf << endl;
}

int main() {
  srand(time(NULL));
  cerr << setprecision(10) << fixed;
  assert(read());
  solve();
  return 0;
}

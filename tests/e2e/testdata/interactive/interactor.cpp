#include "testlib.h"
#include <bits/stdc++.h>

using namespace std;

void upd(int &lf, int &rg, int x, int y) {
  if (x > y)
    return;
  lf = max(lf, x);
  rg = min(rg, y);
}

void send(string x) {
  cout << x << endl;
  fflush(stdout);
}

const int INF = 1000'000'000;

int main(int argc, char *argv[]) {
  registerInteraction(argc, argv);

  int x = inf.readInt();
  int n = inf.readInt();
  cout << n << endl << flush;
  int lf = 1, rg = n;

  int queries = 0;
  while (true) {
    bool is_answer = false;
    string cur = ouf.readToken("!|[1-9][0-9]{0,8}");
    int last;
    if (cur != "!") {
      InStream tmp(ouf, cur);
      last = tmp.readInt(-INF, INF);
      queries++;
    } else {
      is_answer = true;
      last = ouf.readInt(-INF, INF);
    }

    if (last < 1 || last > n)
      quitf(_pe, "number %d from stdin is out of range [%d, %d]", last, 1, n);

    if (is_answer) {
      if (last == x && lf == rg) {
        tout << queries << endl;
        quitf(_ok, "number is guessed.");
      } else if (last == x && lf != rg)
        quitf(_wa, "number is but it was made in a random way");
      else
        quitf(_wa, "guessed number is incorrect");
    }

    if (x < last) {
      send("<");
      upd(lf, rg, 1, last - 1);
    } else {
      send(">=");
      upd(lf, rg, last, n);
    }
  }
}
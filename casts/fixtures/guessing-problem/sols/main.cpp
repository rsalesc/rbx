#include <bits/stdc++.h>

using namespace std;

// Binary search: at most ceil(log2(1000)) = 10 guesses, exactly the budget.
int main() {
    int n;
    cin >> n;

    int lo = 1, hi = n;
    while (true) {
        int mid = lo + (hi - lo) / 2;
        cout << "? " << mid << endl;

        char response;
        cin >> response;
        if (response == '=') return 0;
        if (response == '<') {
            lo = mid + 1;
        } else {
            hi = mid - 1;
        }
    }
}

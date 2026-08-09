#include <bits/stdc++.h>

using namespace std;

// Scans upwards instead of binary searching, so it burns its whole guess
// budget without finding a large secret. It stops at the budget rather than
// looping forever, so the interaction always terminates.
int main() {
    int n;
    cin >> n;

    for (int guess = 1; guess <= min(n, 10); guess++) {
        cout << "? " << guess << endl;

        char response;
        if (!(cin >> response)) return 0;
        if (response == '=') return 0;
    }
    return 0;
}

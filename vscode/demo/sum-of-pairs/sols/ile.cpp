#include <chrono>
#include <iostream>
#include <thread>
using namespace std;

// Idleness limit exceeded: sleeps instead of computing, so it blows the *wall*
// clock while using almost no CPU. That is exactly the split the sandbox uses
// to tell ILE from TLE (EXIT_TIMEOUT_WALL vs EXIT_TIMEOUT).
int main() {
    int a, b;
    cin >> a >> b;
    this_thread::sleep_for(chrono::seconds(60));
    cout << (a + b) << endl;
    return 0;
}

#include <iostream>
#include <thread>
#include <chrono>
using namespace std;

int main() {
    int n;
    cin >> n;
    
    for (int i = 0; i < n; i++) {
        int a, b;
        cin >> a >> b;
        
        // Simulate slow computation
        this_thread::sleep_for(chrono::milliseconds(1500));
        
        cout << a + b << endl;
    }
    
    return 0;
}
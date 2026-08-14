#include <iostream>
#include <cstdlib>
using namespace std;

int main() {
    int n;
    if (!(cin >> n)) {
        cerr << "Failed to read n" << endl;
        return 1;
    }
    
    if (n < 1 || n > 1000) {
        cerr << "n must be between 1 and 1000" << endl;
        return 1;
    }
    
    for (int i = 0; i < n; i++) {
        int a, b;
        if (!(cin >> a >> b)) {
            cerr << "Failed to read pair " << i + 1 << endl;
            return 1;
        }
        
        if (a < 1 || a > 10000 || b < 1 || b > 10000) {
            cerr << "Values must be between 1 and 10000" << endl;
            return 1;
        }
    }
    
    string extra;
    if (cin >> extra) {
        cerr << "Extra data after input" << endl;
        return 1;
    }
    
    return 0;
}
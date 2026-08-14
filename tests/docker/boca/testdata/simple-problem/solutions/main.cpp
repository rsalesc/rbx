#include <iostream>
using namespace std;

int main() {
    int n;
    cin >> n;
    
    for (int i = 0; i < n; i++) {
        int a, b;
        cin >> a >> b;
        cout << a + b << endl;
    }
    
    return 0;
}
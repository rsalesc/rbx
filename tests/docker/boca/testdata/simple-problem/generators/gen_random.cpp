#include <iostream>
#include <random>
using namespace std;

int main(int argc, char* argv[]) {
    if (argc != 4) {
        cerr << "Usage: " << argv[0] << " <n> <min_val> <max_val>" << endl;
        return 1;
    }
    
    int n = atoi(argv[1]);
    int min_val = atoi(argv[2]);
    int max_val = atoi(argv[3]);
    
    random_device rd;
    mt19937 gen(rd());
    uniform_int_distribution<> dis(min_val, max_val);
    
    cout << n << endl;
    for (int i = 0; i < n; i++) {
        int a = dis(gen);
        int b = dis(gen);
        cout << a << " " << b << endl;
    }
    
    return 0;
}
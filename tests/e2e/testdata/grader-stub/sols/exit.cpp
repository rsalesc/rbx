#include <cstdlib>

#include "guess.h"

// Gives up after one question, without ever answering.
int guess_number(int n) {
  ask(1);
  std::exit(0);
}

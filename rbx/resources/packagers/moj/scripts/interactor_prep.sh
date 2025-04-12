#!/bin/bash
function LOG() {
  echo "$*" >&2
}

LOG "Compiling interactor"

g++ -ggdb3 -O2 $(dirname $0)/interactor.cpp -o $1/interactor

LOG "Interactor compiled at $1/interactor"

cp $(dirname $0)/interactor_run.sh $1/interactor_run.sh
LOG "Interactor run script copied to $1/interactor_run.sh"
chmod +x $1/interactor_run.sh

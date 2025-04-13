#!/bin/bash
# ////////////////////////////////////////////////////////////////////////////////
# //BOCA Online Contest Administrator
# //    Copyright (C) 2003-2012 by BOCA Development Team (bocasystem@gmail.com)
# //
# //    This program is free software: you can redistribute it and/or modify
# //    it under the terms of the GNU General Public License as published by
# //    the Free Software Foundation, either version 3 of the License, or
# //    (at your option) any later version.
# //
# //    This program is distributed in the hope that it will be useful,
# //    but WITHOUT ANY WARRANTY; without even the implied warranty of
# //    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# //    GNU General Public License for more details.
# //    You should have received a copy of the GNU General Public License
# //    along with this program.  If not, see <http://www.gnu.org/licenses/>.
# ////////////////////////////////////////////////////////////////////////////////
# // Last modified 21/jul/2012 by cassio@ime.usp.br
#
# This script receives:
# $1 team_output
# $2 sol_output
# $3 problem_input (might be used by some specific checkers, here it is not)
#
# BOCA reads the last line of the standard output
# and pass it to judges
#
if [ ! -r "$1" -o ! -r "$2" ]; then
  echo "Parameter problem"
  exit 43
fi

CHECKERSOURCE=$(dirname "$0")/checker.cpp

if [ ! -r "$CHECKERSOURCE" ]; then
  echo "Checker source not found"
  exit 47
fi

WORKDIRBASE=$(dirname "$1")
WORKDIR=$WORKDIRBASE/cagefiles/
CHECKERHASH={{checkerHash}}
CHECKERPATH=$WORKDIRBASE/$CHECKERHASH

# Get basename of the input file.
FILE=$(basename $3)
STDERRLOG=$WORKDIR/$FILE-stderr

echo "input stderr $STDERRLOG "
if [[ -e $STDERRLOG ]]; then
  INTERACTOREXITCODE=$(grep '^interactor exitcode' $STDERRLOG | awk '{print $NF}')
  echo "interactor exitcode = $INTERACTOREXITCODE"
  if [[ -n $INTERACTOREXITCODE ]]; then
    if [[ $INTERACTOREXITCODE -eq 1 ]]; then
      echo "interactor return wrong answer"
      exit 6
    elif [[ $INTERACTOREXITCODE -eq 2 ]]; then
      echo "interactor invalid input"
      exit 6
    elif [[ $INTERACTOREXITCODE -eq 3 ]]; then
      echo "interactor failed with exit code 3"
      exit 43
    else
      echo "interactor failed with exit code $INTERACTOREXITCODE"
      exit 47
    fi
  fi
fi

lock() {
  MAX_ATTEMPTS=100
  ATTEMPTS=0
  while ! ln -s $CHECKERSOURCE $CHECKERPATH.lock 2>/dev/null; do
    sleep 1
    ATTEMPTS=$((ATTEMPTS + 1))
    if [ $ATTEMPTS -ge $MAX_ATTEMPTS ]; then
      echo "Failed to retrieve checker lock"
      exit 47
    fi
  done
}

unlock() {
  rm -rf $CHECKERPATH.lock
}

compile_checker() {
  cc=$(which g++)
  [ -x "$cc" ] || cc=/usr/bin/g++
  if [ ! -x "$cc" ]; then
    echo "$cc not found or it's not executable"
    exit 47
  fi

  lock
  if [ ! -x "$CHECKERPATH" ]; then
    $cc {{rbxFlags}} $CHECKERSOURCE -o $CHECKERPATH
    chmod 0755 "$CHECKERPATH"
  fi
  unlock
}

if [ ! -x "$CHECKERPATH" ]; then
  compile_checker
fi

# Next lines of this script just compares team_output and sol_output,
# although it is possible to change them to more complex evaluations.
output=$($CHECKERPATH $3 $1 $2 2>&1 >/dev/null)
EC=$?

echo "checker exitcode = $EC"
echo "$output"

if [ $EC -eq 0 ]; then
  echo "checker found no differences"
  exit 4
elif [ $EC -eq 1 ]; then
  echo "checker found differences"
  exit 6
elif [ $EC -eq 2 ]; then
  echo "checker found invalid output"
  exit 6
elif [ $EC -ne 3 ]; then
  echo "judge failed with $EC"
  exit 43
fi

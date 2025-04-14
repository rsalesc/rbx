#!/bin/bash
if [ ! -r "$1" -o ! -r "$2" ]; then
  echo "Parameter problem"
  exit 43
fi

INTERACTOREXITCODE=$(grep '^testlib exitcode' "$1" | awk '{print $NF}')
if [[ -n $INTERACTOREXITCODE ]]; then
  echo "interactor exitcode = $INTERACTOREXITCODE"
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

# Next lines of this script just compares team_output and sol_output,
# although it is possible to change them to more complex evaluations.
output=$(./checker.exe $3 $1 $2 2>&1 >/dev/null)
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
elif [ $EC -eq 3 ]; then
  echo "judge failed with $EC"
  exit 43
else
  echo "judge failed with $EC"
  exit 47
fi

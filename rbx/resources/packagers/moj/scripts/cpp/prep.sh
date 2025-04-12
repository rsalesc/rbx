#!/bin/bash

INTERACTOR_PREP=$PROBLEMTEMPLATEDIR/scripts/interactor_prep.sh

[[ -e $INTERACTOR_PREP ]] && $INTERACTOR_PREP $1

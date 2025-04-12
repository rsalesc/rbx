#!/bin/bash

[[ -e /etc/java-21-openjdk/ ]] && EXTRABINDINGS+="-b /etc/java-21-openjdk/"
[[ -e /etc/java ]] && EXTRABINDINGS+=" -b /etc/java"

INTERACTOR_PREP=$PROBLEMTEMPLATEDIR/scripts/interactor_prep.sh

[[ -e $INTERACTOR_PREP ]] && $INTERACTOR_PREP $1

#!/bin/bash

exec 2>/tmp/stderrlog >/tmp/out
cd /tmp/rwdir

cat >Makefile <<'EOF'

SRC=$(wildcard *.cpp)
CXXFLAGS={{rbxFlags}}

all: $(patsubst %.cpp,%,${SRC})

%: %.cpp
	@g++ ${CXXFLAGS} $^ -o $@ -lm
	@echo BIN=$@
EOF

unset MAKELEVEL
make

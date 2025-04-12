#!/bin/bash

exec 2>/tmp/stderrlog >/tmp/out
cd /tmp/rwdir

cat >Makefile <<'EOF'

SRC=$(wildcard *.c)
CFLAGS={{rbxFlags}}

all: $(patsubst %.c,%,${SRC})

%: %.c
	@gcc ${CFLAGS} $^ -o $@ -lm
	@echo BIN=$@
EOF

unset MAKELEVEL
make

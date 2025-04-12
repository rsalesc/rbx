#!/bin/bash

exec 2>/tmp/stderrlog > /tmp/out
cd /tmp/rwdir

chmod a+x *py2
echo BIN=$(ls *py2)

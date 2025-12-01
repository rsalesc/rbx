### START OF PIPE COMPILATION
CACHE_DIR="/tmp/boca-cache"
mkdir -p $CACHE_DIR

# Assumes testlib was added by checker
PIPE_PATH="pipe.c"
PIPE_OUT="pipe.exe"

function LOG() {
  echo "$*" >&2
}

# find compiler
cc=$(which gcc)
[ -x "$cc" ] || cc=/usr/bin/gcc
if [ ! -x "$cc" ]; then
  echo "$cc not found or it's not executable"
  exit 47
fi

read -r -d '' PipeContent <<"EOF"
{{pipe_content}}
EOF

printf "%s" "${PipeContent}" >$PIPE_PATH

pipe_hash=($(md5sum $PIPE_PATH))
pipe_cache="$CACHE_DIR/pipe-${pipe_hash}"

echo "Pipe hash: $pipe_hash"
echo "Copying pipe to $CDIR/$PIPE_OUT"
if [ -f "$pipe_cache" ]; then
  echo "Recovering pipe from cache: $pipe_cache"
  cp "$pipe_cache" $PIPE_OUT -f
else
  echo "Compiling pipe: $PIPE_PATH"
  $cc -O2 $PIPE_PATH -o $PIPE_OUT

  if [ $? -ne 0 ]; then
    echo "Pipe could not be compiled"
    exit 47
  fi

  cp $PIPE_OUT "$pipe_cache" -f
fi

chown root.root $PIPE_OUT
chmod 4555 $PIPE_OUT
### END OF PIPE COMPILATION

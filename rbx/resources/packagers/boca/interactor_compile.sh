### START OF INTERACTOR COMPILATION
CACHE_DIR="/tmp/boca-cache"
mkdir -p $CACHE_DIR

# Assumes testlib was added by checker
INTERACTOR_PATH="interactor.cpp"
INTERACTOR_OUT="interactor.exe"

function LOG() {
  echo "$*" >&2
}

# find compiler
cc=$(which g++)
[ -x "$cc" ] || cc=/usr/bin/g++
if [ ! -x "$cc" ]; then
  echo "$cc not found or it's not executable"
  exit 47
fi

{{embedded_files}}

interactor_hash=($(cat {{embedded_hash_inputs}} | md5sum))
interactor_cache="$CACHE_DIR/interactor-${interactor_hash}"

echo "Interactor hash: $interactor_hash"
echo "Copying interactor to $CDIR/$INTERACTOR_OUT"
if [ -f "$interactor_cache" ]; then
  echo "Recovering interactor from cache: $interactor_cache"
  cp "$interactor_cache" $INTERACTOR_OUT -f
else
  echo "Compiling interactor: $INTERACTOR_PATH"
  $cc {{rbxFlags}} $INTERACTOR_PATH -o $INTERACTOR_OUT

  if [ $? -ne 0 ]; then
    echo "Interactor could not be compiled"
    exit 47
  fi

  cp $INTERACTOR_OUT "$interactor_cache" -f
fi

chmod 0755 $INTERACTOR_OUT
### END OF INTERACTOR COMPILATION

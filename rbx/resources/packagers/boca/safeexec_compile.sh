### START OF SAFEEXEC COMPILATION
CACHE_DIR="/tmp/boca-cache"
mkdir -p $CACHE_DIR

# Assumes testlib was added by checker
SAFEEXEC_PATH="safeexec.c"
SAFEEXEC_OUT="safeexec.exe"

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

read -r -d '' SafeexecContent <<"EOF"
{{safeexec_content}}
EOF

printf "%s" "${SafeexecContent}" >$SAFEEXEC_PATH

safeexec_hash=($(md5sum $SAFEEXEC_PATH))
safeexec_cache="$CACHE_DIR/safeexec-${safeexec_hash}"

echo "Safeexec hash: $safeexec_hash"
echo "Copying safeexec to $CDIR/$SAFEEXEC_OUT"
if [ -f "$safeexec_cache" ]; then
  echo "Recovering safeexec from cache: $safeexec_cache"
  cp "$safeexec_cache" $SAFEEXEC_OUT -f
else
  echo "Compiling safeexec: $SAFEEXEC_PATH"
  $cc -O2 $SAFEEXEC_PATH -o $SAFEEXEC_OUT

  if [ $? -ne 0 ]; then
    echo "Safeexec could not be compiled"
    exit 47
  fi

  cp $SAFEEXEC_OUT "$safeexec_cache" -f
fi

chown root.root $SAFEEXEC_OUT
chmod 4555 $SAFEEXEC_OUT
### END OF SAFEEXEC COMPILATION

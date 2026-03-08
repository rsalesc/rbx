### START OF CHECKER COMPILATION
CACHE_DIR="/tmp/boca-cache"
mkdir -p $CACHE_DIR

CDIR=$(pwd)
CHECKER_PATH="checker.cpp"
CHECKER_OUT="checker.exe"

# find compiler
cc=$(which g++)
[ -x "$cc" ] || cc=/usr/bin/g++
if [ ! -x "$cc" ]; then
    echo "$cc not found or it's not executable"
    exit 47
fi
read -r -d '' TestlibContent <<"RBXTESTLIBEOF"
{{testlib_content}}
RBXTESTLIBEOF

read -r -d '' RbxHeaderContent <<"RBXRBXHEADEREOF"
{{rbx_header_content}}
RBXRBXHEADEREOF

read -r -d '' CheckerContent <<"RBXCHECKEREOF"
{{checker_content}}
RBXCHECKEREOF

printf "%s" "${TestlibContent}" >testlib.h
printf "%s" "${RbxHeaderContent}" >rbx.h
printf "%s" "${CheckerContent}" >$CHECKER_PATH

checker_hash=($(cat $CHECKER_PATH rbx.h testlib.h | md5sum))
checker_cache="$CACHE_DIR/checker-${checker_hash}"

echo "Polygon checker hash: $checker_hash"
echo "Copying polygon checker to $CDIR/$CHECKER_OUT"
if [ -f "$checker_cache" ]; then
    echo "Recovering polygon checker from cache: $checker_cache"
    cp "$checker_cache" $CHECKER_OUT -f
else
    echo "Compiling polygon checker: $CHECKER_PATH"
    $cc {{rbxFlags}} $CHECKER_PATH -o $CHECKER_OUT

    if [ $? -ne 0 ]; then
        echo "Checker could not be compiled"
        exit 47
    fi

    cp $CHECKER_OUT "$checker_cache" -f
fi

chmod 0755 $CHECKER_OUT
### END OF CHECKER COMPILATION

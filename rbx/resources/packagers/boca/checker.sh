### START OF CHECKER COMPILATION
CHECKER_PATH="checker.cpp"
CHECKER_OUT="../checker.exe"

# find compiler
cc=`which g++`
[ -x "$cc" ] || cc=/usr/bin/g++
if [ ! -x "$cc" ]; then
    echo "$cc not found or it's not executable"
    exit 47
fi
read -r -d '' TestlibContent <<"EOF"
{{testlib_content}}
EOF
  
read -r -d '' CheckerContent <<"EOF"
{{checker_content}}
EOF

printf "%s" "${TestlibContent}" > testlib.h
printf "%s" "${CheckerContent}" > $CHECKER_PATH

checker_hash=($(md5sum $CHECKER_PATH))
checker_cache="/tmp/boca-chk-${checker_hash}"

echo "Polygon checker hash: $checker_hash"
if [ -f "$checker_cache" ]; then
    echo "Recovering polygon checker from cache: $checker_cache"
    cp "$checker_cache" $CHECKER_OUT -f
else
    echo "Compiling polygon checker: $CHECKER_PATH"
    $cc {{stdcpp}} -static -O2 -lm $CHECKER_PATH -o $CHECKER_OUT
    
    if [ $? -ne 0 ]; then
        echo "Checker could not be compiled"
        exit 47
    fi

    cp $CHECKER_OUT "$checker_cache" -f
fi

chmod 0755 $CHECKER_OUT
### END OF CHECKER COMPILATION
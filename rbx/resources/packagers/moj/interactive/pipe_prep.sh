
# ---------------------------------------------------------------------------
# EXPERIMENTAL (rbx package moj --experimental): build the pipe runner next to
# the arbiter. Appended by rbx to mojtools' prep stub above, so it is SOURCED on
# the judge host the same way, with $1 = the work dir (/tmp/dir in the jail):
# no `exit`, only messages on stderr.
#
# scripts/pipe.c is BOCA's pipe.c. It is compiled the way mojtools' own
# interactive/prep.sh compiles the arbiter -- the host's gcc, or else the jail
# rootfs's through bwrap -- statically, and cached by source + compiler.
# ---------------------------------------------------------------------------
_rbx_src="$PROBLEMTEMPLATEDIR/scripts/pipe.c"
if [[ -f "$_rbx_src" ]]; then
  _rbx_cache="$PROBLEMTEMPLATEDIR/.rbx-pipe-cache"
  _rbx_cc=""
  [[ -n "${CAGE_ROOT:-}" && -x "$CAGE_ROOT/usr/bin/gcc" ]] \
    && _rbx_cc="$CAGE_ROOT $(stat -c %Y "$CAGE_ROOT/usr/bin/gcc" 2>/dev/null)"
  _rbx_hash="$(cat "$_rbx_src" <(gcc --version 2>/dev/null || true) <(printf '%s\n' "$_rbx_cc") \
               2>/dev/null | sha256sum | cut -c1-16)"
  _rbx_bin="$_rbx_cache/pipe.$_rbx_hash"
  if [[ ! -x "$_rbx_bin" ]]; then
    mkdir -p "$_rbx_cache" 2>/dev/null
    {
      flock 9 2>/dev/null || true
      if [[ ! -x "$_rbx_bin" ]]; then
        find "$_rbx_cache" -maxdepth 1 -name 'pipe.*' -delete 2>/dev/null
        if command -v gcc >/dev/null 2>&1; then
          gcc -O2 -static -o "$_rbx_cache/pipe.new" "$_rbx_src" 2> "$_rbx_cache/compile.log" \
            && mv -f "$_rbx_cache/pipe.new" "$_rbx_bin" && chmod +x "$_rbx_bin"
        elif [[ -n "$_rbx_cc" ]] && command -v bwrap >/dev/null 2>&1; then
          bwrap --die-with-parent --ro-bind "$CAGE_ROOT" / --dev /dev --proc /proc --tmpfs /tmp \
                --setenv TMPDIR /tmp \
                --ro-bind "$_rbx_src" /tmp/pipe.c --bind "$_rbx_cache" /tmp/out --chdir /tmp \
                /usr/bin/gcc -O2 -static -o /tmp/out/pipe.new /tmp/pipe.c \
                2> "$_rbx_cache/compile.log" \
            && mv -f "$_rbx_cache/pipe.new" "$_rbx_bin" && chmod +x "$_rbx_bin"
        else
          echo "rbx prep: no gcc to build pipe.c (host without gcc and no CAGE_ROOT toolchain)" >&2
        fi
        [[ -x "$_rbx_bin" ]] || { echo "rbx prep: FAILED to build pipe.c:" >&2; cat "$_rbx_cache/compile.log" >&2 2>/dev/null; }
      fi
    } 9>"$_rbx_cache/.lock"
  fi
  [[ -x "$_rbx_bin" ]] && cp -f "$_rbx_bin" "$1/pipe" && chmod +x "$1/pipe"
fi
unset _rbx_src _rbx_cache _rbx_cc _rbx_hash _rbx_bin

# Register `rbx <tab>` completion for THIS zsh session only -- nothing is written
# to your system (no ~/.zshrc edits, no files installed). It tests the fast
# completion engine (#333) using this worktree's build.
#
#   Usage:   source scripts/try-completion-zsh.sh
#   Custom binary:   RBX_BIN=/path/to/rbx source scripts/try-completion-zsh.sh
#   Undo:    compdef -d rbx        (or just close the shell)
#
# Then try:  rbx <tab>   rbx pa<tab>   rbx package <tab>   rbx tool convert --language <tab>
#
# Note: this only changes how <tab> COMPLETES `rbx`; actually running `rbx ...`
# still uses whatever `rbx` is on your PATH.

# Resolve the rbx binary to complete against (defaults to THIS worktree's venv build).
_rbx_try_src="${(%):-%x}"
[ -z "$_rbx_try_src" ] && _rbx_try_src="$0"
_rbx_try_dir="${_rbx_try_src:A:h:h}"
_rbx_try_bin="$_rbx_try_dir/.venv/bin/rbx"
# `source` is a special builtin, so `RBX_BIN=... source ...` (or a previous
# source of THIS or another checkout's script) leaves RBX_BIN set in the shell --
# an inherited value then silently shadows the binary you mean to test (e.g. the
# main checkout's `.venv/bin/rbx` shadowing this worktree's build). Every
# try-completion script sets RBX_BIN to some `<checkout>/.venv/bin/rbx`, so when
# THIS checkout has its own built binary, treat any inherited value of that shape
# that isn't ours as stale and prefer ours. A genuine custom override -- a path
# that is NOT a `.venv/bin/rbx` -- is still honored.
if [[ -z "$RBX_BIN" ]]; then
    RBX_BIN="$_rbx_try_bin"
elif [[ -x "$_rbx_try_bin" && "$RBX_BIN" != "$_rbx_try_bin" && "$RBX_BIN" == *"/.venv/bin/rbx" ]]; then
    print -u2 "note: ignoring stale RBX_BIN ($RBX_BIN); using this checkout's binary"
    RBX_BIN="$_rbx_try_bin"
fi

if [[ ! -x "$RBX_BIN" ]]; then
    print -u2 "rbx binary not found/executable at: $RBX_BIN"
    print -u2 "Run 'uv sync' in the worktree, or set RBX_BIN=/path/to/rbx and re-source."
    return 1
fi

# Make sure zsh's completion system is initialised (compdef / _describe / compadd).
if ! whence compdef >/dev/null 2>&1; then
    autoload -Uz compinit && compinit -u
fi

_rbx_fast_completion() {
    local -a completions desc_values desc_displays response
    local want_files want_dirs
    response=("${(@f)$(
        env COMP_WORDS="${words[*]}" COMP_CWORD=$((CURRENT - 1)) \
            _RBX_COMPLETE=complete_zsh "$RBX_BIN" 2>/dev/null
    )}")

    local type key descr
    # Items arrive as flat (type, value, help) triples, one per line.
    for type key descr in ${response}; do
        if [[ "$type" == "plain" ]]; then
            if [[ "$descr" == "_" ]]; then
                completions+=("$key")
            else
                desc_values+=("$key")
                desc_displays+=("$key -- $descr")
            fi
        elif [[ "$type" == "dir" ]]; then
            want_dirs=1
        elif [[ "$type" == "file" ]]; then
            want_files=1
        fi
    done

    # Add dynamic candidates (e.g. solutions) BEFORE handing off to file
    # completion so they rank ahead of the directory listing (file-union, #575).
    # Use `compadd -d` (not _describe) so insertion order survives even when items
    # share a description (several "ACCEPTED" solutions) -- @main stays first,
    # @boca last.
    if [ -n "$desc_values" ]; then
        compadd -U -V unsorted -l -d desc_displays -a desc_values
    fi
    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
    [[ -n "$want_dirs" ]] && _path_files -/
    [[ -n "$want_files" ]] && _path_files -f
}

compdef _rbx_fast_completion rbx

print "rbx <tab> completion registered for this zsh session."
print "  binary:  $RBX_BIN"
print "Try:     rbx <tab>   rbx pa<tab>   rbx package <tab>   rbx tool convert --language <tab>"
print "Remove:  compdef -d rbx"

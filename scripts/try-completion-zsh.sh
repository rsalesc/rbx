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

# Resolve the rbx binary to complete against (defaults to this worktree's venv build).
_rbx_try_src="${(%):-%x}"
[ -z "$_rbx_try_src" ] && _rbx_try_src="$0"
_rbx_try_dir="${_rbx_try_src:A:h:h}"
: ${RBX_BIN:="$_rbx_try_dir/.venv/bin/rbx"}

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
    local -a completions completions_with_descriptions response
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
                completions_with_descriptions+=("$key":"$descr")
            fi
        elif [[ "$type" == "dir" ]]; then
            _path_files -/
        elif [[ "$type" == "file" ]]; then
            _path_files -f
        fi
    done

    if [ -n "$completions_with_descriptions" ]; then
        _describe -V unsorted completions_with_descriptions -U
    fi
    if [ -n "$completions" ]; then
        compadd -U -V unsorted -a completions
    fi
}

compdef _rbx_fast_completion rbx

print "rbx <tab> completion registered for this zsh session."
print "  binary:  $RBX_BIN"
print "Try:     rbx <tab>   rbx pa<tab>   rbx package <tab>   rbx tool convert --language <tab>"
print "Remove:  compdef -d rbx"

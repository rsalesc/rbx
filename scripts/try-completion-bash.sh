# Register `rbx <tab>` completion for THIS bash session only -- nothing is written
# to your system (no ~/.bashrc edits, no files installed). It tests the fast
# completion engine (#333) using this worktree's build.
#
#   Usage:   source scripts/try-completion-bash.sh
#   Custom binary:   RBX_BIN=/path/to/rbx source scripts/try-completion-bash.sh
#   Undo:    complete -r rbx        (or just close the shell)
#
# Then try:  rbx <tab>   rbx pa<tab>   rbx package <tab>   rbx tool convert --language <tab>
#
# Note: this only changes how <tab> COMPLETES `rbx`; actually running `rbx ...`
# still uses whatever `rbx` is on your PATH.

# Resolve the rbx binary to complete against (defaults to THIS worktree's venv build).
if [ -n "${BASH_SOURCE[0]:-}" ]; then
    _rbx_try_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
else
    _rbx_try_dir="$(pwd)"
fi
_rbx_try_bin="$_rbx_try_dir/.venv/bin/rbx"
# `source` is a special builtin, so `RBX_BIN=... source ...` (or a previous
# source) leaves RBX_BIN set in the shell -- a value left over from sourcing a
# DIFFERENT worktree's script would shadow this one. Default to this worktree's
# binary, and if an inherited RBX_BIN points at another worktree, treat it as
# stale and recompute. A genuine override outside any worktree is still honored.
if [ -z "${RBX_BIN:-}" ]; then
    RBX_BIN="$_rbx_try_bin"
elif [[ "$RBX_BIN" == *"/.claude/worktrees/"* && "$RBX_BIN" != "$_rbx_try_bin" ]]; then
    echo "note: ignoring stale RBX_BIN from another worktree ($RBX_BIN)" >&2
    RBX_BIN="$_rbx_try_bin"
fi

if [ ! -x "$RBX_BIN" ]; then
    echo "rbx binary not found/executable at: $RBX_BIN" >&2
    echo "Run 'uv sync' in the worktree, or set RBX_BIN=/path/to/rbx and re-source." >&2
    return 1 2>/dev/null || exit 1
fi

_rbx_fast_completion() {
    local IFS=$'\n'
    local response type value completion
    response="$(
        env COMP_WORDS="${COMP_WORDS[*]}" COMP_CWORD="$COMP_CWORD" \
            _RBX_COMPLETE=complete_bash "$RBX_BIN" 2>/dev/null
    )"
    COMPREPLY=()
    for completion in $response; do
        IFS=',' read -r type value <<<"$completion"
        if [[ $type == 'dir' ]]; then
            COMPREPLY=()
            command -v compopt >/dev/null 2>&1 && compopt -o dirnames
        elif [[ $type == 'file' ]]; then
            COMPREPLY=()
            command -v compopt >/dev/null 2>&1 && compopt -o default
        elif [[ $type == 'plain' ]]; then
            COMPREPLY+=("$value")
        fi
    done
    return 0
}

# `-o nosort` needs bash >= 4.4; fall back gracefully on older bash (e.g. macOS /bin/bash 3.2).
complete -o nosort -F _rbx_fast_completion rbx 2>/dev/null ||
    complete -F _rbx_fast_completion rbx

echo "rbx <tab> completion registered for this session."
echo "  binary:  $RBX_BIN"
if [ "${BASH_VERSINFO[0]:-0}" -lt 4 ]; then
    echo "  note:    your bash is ${BASH_VERSION:-<3.x>}; file/dir fallback needs bash >= 4.1." >&2
fi
echo "Try:     rbx <tab>   rbx pa<tab>   rbx package <tab>   rbx tool convert --language <tab>"
echo "Remove:  complete -r rbx"

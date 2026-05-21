#!/usr/bin/env bash
#
# activate-venv.sh — activate the Python venv of a worktree or branch.
#
# Usage:
#   source ./activate-venv.sh [-b] <name>
#   ./activate-venv.sh [-b] <name>
#
# By default <name> is a worktree directory name; it is looked up under
# .worktrees/<name> and then .claude/worktrees/<name> (first match wins).
#
# With -b, <name> is a git branch; the worktree that currently has that
# branch checked out is used instead.
#
# For the activation to persist in your current shell you must SOURCE this
# script:  `source ./activate-venv.sh my-feature`. When run directly it
# instead drops you into a new sub-shell with the venv activated.

# --- detect whether we were sourced (works in bash and zsh) -----------------
_av_sourced=0
if [ -n "${ZSH_VERSION:-}" ]; then
  case "${ZSH_EVAL_CONTEXT:-}" in
    *:file*) _av_sourced=1 ;;
  esac
  # zsh-specific way to read this file's own path, hidden from bash's parser.
  _av_self="$(eval 'printf "%s" "${(%):-%x}"')"
elif [ -n "${BASH_VERSION:-}" ]; then
  [ "${BASH_SOURCE[0]}" != "$0" ] && _av_sourced=1
  _av_self="${BASH_SOURCE[0]}"
else
  _av_self="$0"
fi

# --- argument parsing -------------------------------------------------------
_av_usage() {
  cat >&2 <<'EOF'
Usage: source ./activate-venv.sh [-b] <name>
       ./activate-venv.sh [-b] <name>

  <name>   worktree directory name (under .worktrees or .claude/worktrees)
  -b       treat <name> as a git branch and use its checked-out worktree
EOF
}

_av_by_branch=0
_av_name=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -b|--branch) _av_by_branch=1 ;;
    -h|--help) _av_usage; return 0 2>/dev/null || exit 0 ;;
    --) shift; _av_name="${1:-}"; break ;;
    -*) echo "activate-venv: unknown option: $1" >&2; _av_usage
        return 1 2>/dev/null || exit 1 ;;
    *) _av_name="$1" ;;
  esac
  shift
done

if [ -z "$_av_name" ]; then
  echo "activate-venv: missing <name>" >&2
  _av_usage
  return 1 2>/dev/null || exit 1
fi

# --- locate the repository root (this script lives there) -------------------
_av_root="$(cd "$(dirname "$_av_self")" >/dev/null 2>&1 && pwd)"

# --- resolve the target worktree directory ----------------------------------
_av_wt=""
if [ "$_av_by_branch" -eq 1 ]; then
  # Find the worktree whose checked-out branch matches <name>.
  _av_wt="$(git -C "$_av_root" worktree list --porcelain 2>/dev/null | awk -v b="$_av_name" '
    /^worktree / { path = substr($0, 10); next }
    /^branch /   { ref = substr($0, 8)
                   if (ref == "refs/heads/" b) { print path; exit } }')"
  if [ -z "$_av_wt" ]; then
    echo "activate-venv: no worktree found with branch '$_av_name'" >&2
    return 1 2>/dev/null || exit 1
  fi
else
  for _av_base in "$_av_root/.worktrees" "$_av_root/.claude/worktrees"; do
    if [ -d "$_av_base/$_av_name" ]; then
      _av_wt="$_av_base/$_av_name"
      break
    fi
  done
  if [ -z "$_av_wt" ]; then
    echo "activate-venv: no worktree named '$_av_name' under .worktrees or .claude/worktrees" >&2
    return 1 2>/dev/null || exit 1
  fi
fi

# --- locate and run the activation script -----------------------------------
_av_activate="$_av_wt/.venv/bin/activate"
if [ ! -f "$_av_activate" ]; then
  echo "activate-venv: no venv at $_av_activate (run 'uv sync' in that worktree?)" >&2
  return 1 2>/dev/null || exit 1
fi

if [ "$_av_sourced" -eq 1 ]; then
  echo "activate-venv: activating $_av_wt"
  # shellcheck disable=SC1090
  . "$_av_activate"
else
  echo "activate-venv: opening a sub-shell with $_av_wt activated (exit to leave)"
  exec "${SHELL:-bash}" -c '. "$1"; exec "${SHELL:-bash}" -i' _ "$_av_activate"
fi

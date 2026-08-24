#!/usr/bin/env bash
#
# activate-venv.sh — activate the Python venv of a worktree or branch.
#
# Usage:
#   source ./activate-venv.sh [-b] [<name>]
#   ./activate-venv.sh [-b] [<name>]
#
# With no argument, the venv of the root repository (the one this script
# lives in) is used.
#
# A bare <name> is a worktree directory name; it is looked up under
# .worktrees/<name> and then .claude/worktrees/<name> (first match wins).
# As a convenience, a bare <name> that starts with "worktree-" and doesn't
# match a directory is treated as a branch (see -b): harness-created worktrees
# live under .claude/worktrees/<name> but their branch is "worktree-<name>", so
# passing the branch name (e.g. worktree-issue-535-preset-registry) activates
# that worktree directly.
#
# A <name> that contains a slash is treated as a path to a worktree,
# relative to the root repo (e.g. .claude/worktrees/foo) or absolute.
#
# With -b, <name> is a git branch; the worktree that currently has that branch
# checked out is used instead. The branch is never checked out — we only look
# up the existing worktree that already has it.
#
# A <name> that is a GitHub pull request URL (…/pull/N) is resolved, via the gh
# CLI, to the PR's head branch and then to the worktree that has it checked out
# — paste a PR URL to jump into the worktree you're reviewing. Requires gh, and
# the PR's branch must be checked out in a local worktree.
#
# ./run-extension.sh takes the same <name> in the same way — both scripts share
# scripts/worktree-lib.sh.
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
elif [ -n "${BASH_VERSION:-}" ]; then
  [ "${BASH_SOURCE[0]}" != "$0" ] && _av_sourced=1
fi

# --- locate the repository root (this script lives there) -------------------
if [ -n "${ZSH_VERSION:-}" ]; then
  # zsh-specific way to read this file's own path, hidden from bash's parser.
  _av_self="$(eval 'printf "%s" "${(%):-%x}"')"
elif [ -n "${BASH_VERSION:-}" ]; then
  _av_self="${BASH_SOURCE[0]}"
else
  _av_self="$0"
fi
_av_root="$(cd "$(dirname "$_av_self")" >/dev/null 2>&1 && pwd)"

# shellcheck source=scripts/worktree-lib.sh
. "$_av_root/scripts/worktree-lib.sh" || return 1 2>/dev/null || exit 1
WT_PROG="activate-venv"

# --- argument parsing -------------------------------------------------------
_av_usage() {
  cat >&2 <<EOF
Usage: source ./activate-venv.sh [-b] [<name>]
       ./activate-venv.sh [-b] [<name>]

$(wt_name_help '  ')
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

if [ -z "$_av_name" ] && [ "$_av_by_branch" -eq 1 ]; then
  echo "activate-venv: -b requires a branch name" >&2
  _av_usage
  return 1 2>/dev/null || exit 1
fi

# --- resolve the target worktree directory ----------------------------------
_av_wt="$(wt_resolve "$_av_root" "$_av_name" "$_av_by_branch")" || {
  return 1 2>/dev/null || exit 1
}

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

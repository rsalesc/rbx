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
Usage: source ./activate-venv.sh [-b] [<name>]
       ./activate-venv.sh [-b] [<name>]

  (no name)   use the root repository's venv
  <name>      worktree directory name (under .worktrees or .claude/worktrees),
              or a path to a worktree relative to the root repo (e.g.
              .claude/worktrees/foo) or absolute; a "worktree-" prefixed name
              that matches no directory is resolved as a branch (see -b)
  <pr-url>    a GitHub pull request URL (…/pull/N); uses the worktree that has
              the PR's head branch checked out (needs gh)
  -b <name>   treat <name> as a git branch and use its checked-out worktree
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

# --- locate the repository root (this script lives there) -------------------
_av_root="$(cd "$(dirname "$_av_self")" >/dev/null 2>&1 && pwd)"

# --- resolve the target worktree directory ----------------------------------
_av_wt=""          # resolved worktree path, once known
_av_branch=""      # set when <name> should be resolved via git branch lookup
_av_branch_from="" # human description of where the branch came from, if indirect
if [ "$_av_by_branch" -eq 1 ]; then
  _av_branch="$_av_name"
elif [ -z "$_av_name" ]; then
  # No name: use the root repository this script lives in.
  _av_wt="$_av_root"
else
  case "$_av_name" in
    *://*/pull/*)
      # A GitHub pull request URL: resolve its head branch via gh, then treat it
      # like a branch (it must be checked out in a local worktree). The branch is
      # only looked up, never checked out.
      if ! command -v gh >/dev/null 2>&1; then
        echo "activate-venv: gh (GitHub CLI) is required to resolve a pull request URL" >&2
        return 1 2>/dev/null || exit 1
      fi
      _av_branch="$(gh pr view "$_av_name" --json headRefName -q .headRefName)"
      if [ -z "$_av_branch" ]; then
        echo "activate-venv: could not resolve a head branch for pull request '$_av_name' (check the URL and 'gh auth status')" >&2
        return 1 2>/dev/null || exit 1
      fi
      _av_branch_from="pull request $_av_name"
      ;;
    */*)
      # A path to a worktree: relative to the root repo, or absolute.
      case "$_av_name" in
        /*) _av_wt="$_av_name" ;;
        *)  _av_wt="$_av_root/$_av_name" ;;
      esac
      if [ ! -d "$_av_wt" ]; then
        echo "activate-venv: no such directory: $_av_wt" >&2
        return 1 2>/dev/null || exit 1
      fi
      ;;
    *)
      # A bare worktree directory name.
      for _av_base in "$_av_root/.worktrees" "$_av_root/.claude/worktrees"; do
        if [ -d "$_av_base/$_av_name" ]; then
          _av_wt="$_av_base/$_av_name"
          break
        fi
      done
      # No directory matched. A "worktree-<name>" branch (what the harness names
      # its worktree branches) maps to the worktree dir <name>, so resolve it as
      # a branch and activate that existing worktree directly.
      if [ -z "$_av_wt" ]; then
        case "$_av_name" in
          worktree-*) _av_branch="$_av_name" ;;
          *) echo "activate-venv: no worktree named '$_av_name' under .worktrees or .claude/worktrees" >&2
             return 1 2>/dev/null || exit 1 ;;
        esac
      fi
      ;;
  esac
fi

# Resolve a branch name to the worktree that currently has it checked out. This
# only reads the worktree list; it never checks the branch out anywhere.
if [ -n "$_av_branch" ]; then
  _av_wt="$(git -C "$_av_root" worktree list --porcelain 2>/dev/null | awk -v b="$_av_branch" '
    /^worktree / { path = substr($0, 10); next }
    /^branch /   { ref = substr($0, 8)
                   if (ref == "refs/heads/" b) { print path; exit } }')"
  if [ -z "$_av_wt" ]; then
    echo "activate-venv: no worktree found with branch '$_av_branch'${_av_branch_from:+ (from $_av_branch_from)}" >&2
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

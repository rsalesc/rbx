#!/usr/bin/env bash
#
# worktree-lib.sh — resolve a worktree from a name, a path, a branch or a PR.
#
# Sourced by the repository's developer scripts (activate-venv.sh,
# run-extension.sh) so they all accept the same <name> in the same way. It is
# written in POSIX shell so it works when sourced from bash and from zsh.
#
# Functions:
#   wt_name_help <indent>   the shared <name> lines of a script's usage text
#   wt_resolve <root> <name> <by-branch>
#                           echo the worktree directory <name> refers to, with
#                           <root> the repository the calling script lives in
#                           and <by-branch> 1 to read <name> as a git branch
#
# Messages are prefixed with $WT_PROG, which the calling script sets to its own
# name so its errors all look like they came from one script.

# The <name> paragraph of a usage message, indented by $1, so both scripts
# describe the argument they share in the same words.
wt_name_help() {
  _wt_i="${1:-}"
  cat <<EOF
${_wt_i}(no name)   use the root repository this script lives in
${_wt_i}<name>      worktree directory name (under .worktrees or .claude/worktrees),
${_wt_i}            or a path to a worktree relative to the root repo (e.g.
${_wt_i}            .claude/worktrees/foo) or absolute; a "worktree-" prefixed name
${_wt_i}            that matches no directory is resolved as a branch (see -b)
${_wt_i}<pr-url>    a GitHub pull request URL (…/pull/N); uses the worktree that has
${_wt_i}            the PR's head branch checked out (needs gh)
${_wt_i}-b <name>   treat <name> as a git branch and use its checked-out worktree
EOF
  unset _wt_i
}

# Resolve a branch name to the worktree that currently has it checked out. This
# only reads the worktree list; it never checks the branch out anywhere.
_wt_by_branch() {
  _wt_root="$1"
  _wt_branch="$2"
  _wt_from="$3"
  _wt_path="$(git -C "$_wt_root" worktree list --porcelain 2>/dev/null | awk -v b="$_wt_branch" '
    /^worktree / { path = substr($0, 10); next }
    /^branch /   { ref = substr($0, 8)
                   if (ref == "refs/heads/" b) { print path; exit } }')"
  if [ -z "$_wt_path" ]; then
    echo "${WT_PROG:-worktree}: no worktree found with branch '$_wt_branch'${_wt_from:+ (from $_wt_from)}" >&2
    return 1
  fi
  printf '%s' "$_wt_path"
}

# Echo the worktree directory <name> refers to, or fail with a message on
# stderr. Callers report the failure their own way, so this only returns 1.
wt_resolve() {
  _wt_root="$1"
  _wt_name="$2"
  _wt_bybranch="${3:-0}"

  if [ "$_wt_bybranch" -eq 1 ]; then
    _wt_by_branch "$_wt_root" "$_wt_name" ""
    return $?
  fi

  if [ -z "$_wt_name" ]; then
    # No name: use the root repository the calling script lives in.
    printf '%s' "$_wt_root"
    return 0
  fi

  case "$_wt_name" in
    *://*/pull/*)
      # A GitHub pull request URL: resolve its head branch via gh, then treat it
      # like a branch (it must be checked out in a local worktree). The branch is
      # only looked up, never checked out.
      if ! command -v gh >/dev/null 2>&1; then
        echo "${WT_PROG:-worktree}: gh (GitHub CLI) is required to resolve a pull request URL" >&2
        return 1
      fi
      _wt_branch="$(gh pr view "$_wt_name" --json headRefName -q .headRefName)"
      if [ -z "$_wt_branch" ]; then
        echo "${WT_PROG:-worktree}: could not resolve a head branch for pull request '$_wt_name' (check the URL and 'gh auth status')" >&2
        return 1
      fi
      _wt_by_branch "$_wt_root" "$_wt_branch" "pull request $_wt_name"
      return $?
      ;;
    */*)
      # A path to a worktree: relative to the root repo, or absolute.
      case "$_wt_name" in
        /*) _wt_path="$_wt_name" ;;
        *)  _wt_path="$_wt_root/$_wt_name" ;;
      esac
      if [ ! -d "$_wt_path" ]; then
        echo "${WT_PROG:-worktree}: no such directory: $_wt_path" >&2
        return 1
      fi
      printf '%s' "$_wt_path"
      return 0
      ;;
    *)
      # A bare worktree directory name.
      for _wt_base in "$_wt_root/.worktrees" "$_wt_root/.claude/worktrees"; do
        if [ -d "$_wt_base/$_wt_name" ]; then
          printf '%s' "$_wt_base/$_wt_name"
          return 0
        fi
      done
      # No directory matched. A "worktree-<name>" branch (what the harness names
      # its worktree branches) maps to the worktree dir <name>, so resolve it as
      # a branch and use that existing worktree directly.
      case "$_wt_name" in
        worktree-*)
          _wt_by_branch "$_wt_root" "$_wt_name" ""
          return $?
          ;;
        *)
          echo "${WT_PROG:-worktree}: no worktree named '$_wt_name' under .worktrees or .claude/worktrees" >&2
          return 1
          ;;
      esac
      ;;
  esac
}

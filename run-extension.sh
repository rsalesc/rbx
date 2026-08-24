#!/usr/bin/env bash
#
# run-extension.sh — run the VS Code extension under development.
#
# Usage:
#   ./run-extension.sh [-b] [<name>] [-e <editor>]... [-f <folder>] [options]
#
# Builds vscode/ in the worktree <name> names and launches an Extension
# Development Host loading it, so the editor runs the extension *from that
# checkout* — no .vsix, no install, no `rbx vscode install`. This is what
# pressing F5 in vscode/ does, from any terminal and for any worktree.
#
# <name> is resolved exactly as ./activate-venv.sh resolves it (both scripts
# share scripts/worktree-lib.sh): with no name the root repository this script
# lives in, otherwise a worktree directory name, a path, a "worktree-" branch,
# a branch with -b, or a GitHub pull request URL. So the review you already
# have checked out is one command away from running in your editor:
#
#   ./run-extension.sh https://github.com/rsalesc/rbx/pull/723 -e cursor
#
# The extension is always bundled before the editor starts (npm install first
# if node_modules is missing), because a development host pointed at a checkout
# that was never built fails on activation with a missing dist/extension.js.
# Pass --no-build to skip that when you already have `npm run watch` going.

set -euo pipefail

WT_PROG="run-extension"

_re_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
# shellcheck source=scripts/worktree-lib.sh
. "$_re_root/scripts/worktree-lib.sh"

# --- editors ----------------------------------------------------------------
# Keyed the same way as rbx/box/vscode/extension.py, so --editor takes the same
# names as `rbx vscode install --editor`.
_re_editor_binary() {
  case "$1" in
    code) echo "code" ;;
    cursor) echo "cursor" ;;
    windsurf) echo "windsurf" ;;
    codium) echo "codium" ;;
    code-insiders) echo "code-insiders" ;;
    *) return 1 ;;
  esac
}

_re_editor_label() {
  case "$1" in
    code) echo "VS Code" ;;
    cursor) echo "Cursor" ;;
    windsurf) echo "Windsurf" ;;
    codium) echo "VSCodium" ;;
    code-insiders) echo "VS Code Insiders" ;;
  esac
}

# The app bundle each editor installs its CLI inside, so a Mac that never ran
# "Shell Command: Install 'code' command in PATH" still works.
_re_editor_app() {
  case "$1" in
    code) echo "/Applications/Visual Studio Code.app" ;;
    cursor) echo "/Applications/Cursor.app" ;;
    windsurf) echo "/Applications/Windsurf.app" ;;
    codium) echo "/Applications/VSCodium.app" ;;
    code-insiders) echo "/Applications/Visual Studio Code - Insiders.app" ;;
  esac
}

_re_editors="code cursor windsurf codium code-insiders"

# Which editor's integrated terminal we are in, if any. TERM_PROGRAM=vscode is
# set by VS Code *and every fork*, so the app path is what tells them apart —
# the same reasoning as detect_editor() in rbx/box/vscode/extension.py.
_re_detect_editor() {
  [ "${TERM_PROGRAM:-}" = "vscode" ] || return 1
  _re_app="$(printf '%s' "${VSCODE_GIT_ASKPASS_NODE:-${VSCODE_GIT_ASKPASS_MAIN:-}}" | tr '[:upper:]' '[:lower:]')"
  case "$_re_app" in
    *cursor*) echo cursor; return 0 ;;
    *windsurf*) echo windsurf; return 0 ;;
    *codium*) echo codium; return 0 ;;
    *"code - insiders"*) echo code-insiders; return 0 ;;
  esac
  # An integrated terminal that told us nothing else is VS Code.
  echo code
}

# The command that starts <editor>: its CLI on PATH, else the one in its app
# bundle. Fails, with what to do about it, when neither exists.
_re_editor_command() {
  _re_key="$1"
  _re_bin="$(_re_editor_binary "$_re_key")"
  if command -v "$_re_bin" >/dev/null 2>&1; then
    command -v "$_re_bin"
    return 0
  fi
  _re_inapp="$(_re_editor_app "$_re_key")/Contents/Resources/app/bin/$_re_bin"
  if [ -x "$_re_inapp" ]; then
    echo "$_re_inapp"
    return 0
  fi
  echo "$WT_PROG: could not find the '$_re_bin' command for $(_re_editor_label "$_re_key")" >&2
  echo "$WT_PROG: add it from the editor with \"Shell Command: Install '$_re_bin' command in PATH\", or install $(_re_editor_label "$_re_key")" >&2
  return 1
}

# --- argument parsing -------------------------------------------------------
_re_usage() {
  cat >&2 <<EOF
Usage: ./run-extension.sh [-b] [<name>] [-e <editor>]... [-f <folder>] [options]

$(wt_name_help '  ')

  -e, --editor <key>    editor to launch: $(echo "$_re_editors" | tr ' ' ',')
                        (repeatable; defaults to the editor whose terminal this
                        is, else code)
  -f, --folder <path>   folder the development host opens; defaults to the
                        current directory when it holds a problem.rbx.yml or a
                        contest.rbx.yml, else nothing
  -n, --no-build        do not build first (use with 'npm run watch')
  -c, --clean           disable your other extensions in the development host
  -p, --print           print the command instead of running it
  -h, --help            this message
EOF
}

_re_by_branch=0
_re_name=""
_re_editor_keys=""
_re_folder=""
_re_build=1
_re_clean=0
_re_print=0

_re_need_value() {
  if [ "$2" -lt 2 ]; then
    echo "$WT_PROG: $1 requires a value" >&2
    _re_usage
    exit 1
  fi
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    -b|--branch) _re_by_branch=1 ;;
    -e|--editor)
      _re_need_value "$1" "$#"
      _re_editor_keys="$_re_editor_keys $2"
      shift
      ;;
    -f|--folder)
      _re_need_value "$1" "$#"
      _re_folder="$2"
      shift
      ;;
    -n|--no-build) _re_build=0 ;;
    -c|--clean) _re_clean=1 ;;
    -p|--print) _re_print=1 ;;
    -h|--help) _re_usage; exit 0 ;;
    --) shift; _re_name="${1:-}"; break ;;
    -*) echo "$WT_PROG: unknown option: $1" >&2; _re_usage; exit 1 ;;
    *) _re_name="$1" ;;
  esac
  shift
done

if [ -z "$_re_name" ] && [ "$_re_by_branch" -eq 1 ]; then
  echo "$WT_PROG: -b requires a branch name" >&2
  _re_usage
  exit 1
fi

# No editor named: the one whose terminal we are in, else VS Code.
if [ -z "${_re_editor_keys// /}" ]; then
  _re_editor_keys="$(_re_detect_editor || echo code)"
fi

for _re_key in $_re_editor_keys; do
  if ! _re_editor_binary "$_re_key" >/dev/null; then
    echo "$WT_PROG: unknown editor: $_re_key" >&2
    echo "$WT_PROG: known editors: $(echo "$_re_editors" | tr ' ' ',')" >&2
    exit 1
  fi
done

# --- resolve the worktree and its extension ---------------------------------
_re_wt="$(wt_resolve "$_re_root" "$_re_name" "$_re_by_branch")"
_re_ext="$_re_wt/vscode"
if [ ! -f "$_re_ext/package.json" ]; then
  echo "$WT_PROG: no extension at $_re_ext (is $_re_wt an rbx worktree?)" >&2
  exit 1
fi

# --- resolve the folder the host opens --------------------------------------
# A development host with no folder open activates nothing: the extension is
# only awake once it sees a package. Defaulting to the current directory means
# running this from a problem is enough.
if [ -z "$_re_folder" ]; then
  if [ -f "$PWD/problem.rbx.yml" ] || [ -f "$PWD/contest.rbx.yml" ]; then
    _re_folder="$PWD"
  fi
elif [ ! -d "$_re_folder" ]; then
  echo "$WT_PROG: no such folder: $_re_folder" >&2
  exit 1
fi
if [ -n "$_re_folder" ]; then
  _re_folder="$(cd "$_re_folder" >/dev/null 2>&1 && pwd)"
fi

# --- build ------------------------------------------------------------------
# A development host loads dist/extension.js directly from the checkout, so an
# unbuilt (or stale) checkout only fails later, inside the editor, as a failed
# activation. Build before launching rather than after the report.
if [ "$_re_build" -eq 1 ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "$WT_PROG: npm is required to build the extension (or pass --no-build)" >&2
    exit 1
  fi
  if [ ! -d "$_re_ext/node_modules" ]; then
    echo "$WT_PROG: installing npm dependencies in $_re_ext"
    (cd "$_re_ext" && npm install)
  fi
  echo "$WT_PROG: building $_re_ext"
  (cd "$_re_ext" && npm run compile)
fi

if [ ! -f "$_re_ext/dist/extension.js" ]; then
  echo "$WT_PROG: $_re_ext/dist/extension.js is missing — the development host would fail to activate" >&2
  if [ "$_re_build" -eq 0 ]; then
    echo "$WT_PROG: run without --no-build, or 'npm run compile' in $_re_ext" >&2
  fi
  exit 1
fi

# --- launch -----------------------------------------------------------------
for _re_key in $_re_editor_keys; do
  _re_cmd="$(_re_editor_command "$_re_key")"

  set -- --new-window --extensionDevelopmentPath="$_re_ext"
  if [ "$_re_clean" -eq 1 ]; then
    set -- "$@" --disable-extensions
  fi
  if [ -n "$_re_folder" ]; then
    set -- "$@" "$_re_folder"
  fi

  if [ "$_re_print" -eq 1 ]; then
    printf '%q ' "$_re_cmd" "$@"
    printf '\n'
    continue
  fi

  echo "$WT_PROG: launching $(_re_editor_label "$_re_key") with $_re_ext${_re_folder:+ on $_re_folder}"
  "$_re_cmd" "$@"
done

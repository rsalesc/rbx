#!/usr/bin/env bash
#
# Spin up a throwaway DOMjudge server locally, with docker.
#
#   scripts/domjudge/domjudge.sh up          # start it, print the credentials
#   scripts/domjudge/domjudge.sh creds       # print them again
#   scripts/domjudge/domjudge.sh down        # stop it (keeps the database)
#   scripts/domjudge/domjudge.sh nuke        # stop it and drop the database
#
# See README.md in this directory.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$HERE/docker-compose.yml"

DJ_PORT="${DJ_PORT:-12345}"
DJ_VERSION="${DJ_VERSION:-latest}"
export DJ_PORT DJ_VERSION

DOMSERVER_CONTAINER='rbx-dj-domserver'
ADMIN_SECRET='/opt/domjudge/domserver/etc/initial_admin_password.secret'
RESTAPI_SECRET='/opt/domjudge/domserver/etc/restapi.secret'

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '\033[36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33mwarning:\033[0m %s\n' "$*" >&2; }
die() {
  printf '\033[31merror:\033[0m %s\n' "$*" >&2
  exit 1
}

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

require_docker() {
  command -v docker >/dev/null 2>&1 || die 'docker is not installed or not on PATH.'
  docker info >/dev/null 2>&1 || die 'the docker daemon is not running.'
  docker compose version >/dev/null 2>&1 ||
    die 'docker compose (v2) is required; `docker compose version` failed.'
}

usage() {
  cat <<'USAGE'
usage: domjudge.sh <command> [options]

commands:
  up [--with-judgehost] [--bare]   start mariadb + domserver, wait until healthy
  down [--volumes]                 stop the containers (--volumes drops the DB)
  nuke                             down --volumes, plus the judgehost
  restart                          down, then up
  status                           show container/health status
  creds                            print URL, admin password, judgehost password
  logs [service] [-f]              tail logs (default: domserver)
  shell [service]                  open a shell in a container (default: domserver)

options:
  --with-judgehost   also start a judgedaemon (privileged; Linux only, see README)
  --bare             install DOMjudge without the demo contest/teams/problems
                     (only has an effect on a fresh database)

environment:
  DJ_PORT      host port for the web interface (default: 12345)
  DJ_VERSION   image tag for domserver/judgehost (default: latest)
USAGE
}

admin_password() {
  docker exec "$DOMSERVER_CONTAINER" cat "$ADMIN_SECRET" 2>/dev/null | tr -d '\r\n'
}

# restapi.secret looks like:
#   default  http://domserver/api/  judgehost  <password>
# The password is the last whitespace-separated field of the first real line.
judgehost_password() {
  docker exec "$DOMSERVER_CONTAINER" cat "$RESTAPI_SECRET" 2>/dev/null |
    grep -v '^\s*#' | grep -v '^\s*$' | head -n 1 | awk '{print $NF}'
}

print_creds() {
  local admin judge
  admin="$(admin_password || true)"
  judge="$(judgehost_password || true)"

  echo
  bold 'DOMjudge is up:'
  echo "  url:             http://localhost:${DJ_PORT}/"
  echo "  admin user:      admin"
  echo "  admin password:  ${admin:-<not available yet>}"
  echo "  judgehost pass:  ${judge:-<not available yet>}"
  if [[ "${DJ_DB_INSTALL_BARE:-0}" != '1' ]]; then
    echo '  demo accounts:   demo / demo (team), judge / judge (jury)'
  fi
  echo
}

cmd_up() {
  local with_judgehost=0
  local profile_args=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --with-judgehost) with_judgehost=1 ;;
      --bare) export DJ_DB_INSTALL_BARE=1 ;;
      *) die "unknown option for up: $1" ;;
    esac
    shift
  done

  require_docker

  info "pulling images (domjudge/*:${DJ_VERSION})"
  compose pull --quiet mariadb domserver

  info 'starting mariadb + domserver'
  compose up -d --wait mariadb domserver

  print_creds

  if [[ "$with_judgehost" -eq 1 ]]; then
    if [[ "$(uname -s)" != 'Linux' ]]; then
      warn 'the judgehost needs host cgroups and a privileged container; on'
      warn 'macOS/Windows it usually fails to start. Starting it anyway.'
    fi

    local judge_pw
    judge_pw="$(judgehost_password)"
    [[ -n "$judge_pw" ]] || die 'could not read the judgehost password from the domserver.'

    info 'starting judgehost'
    DJ_JUDGEDAEMON_PASSWORD="$judge_pw" compose --profile judgehost up -d judgehost
    info 'judgehost started; check `domjudge.sh logs judgehost` if no judgedaemon shows up'
  else
    info 'no judgehost started (submissions will queue as PENDING).'
    info 'add --with-judgehost to run one -- see the README for the caveats.'
  fi
}

cmd_down() {
  require_docker
  local args=(--profile judgehost down)
  [[ "${1:-}" == '--volumes' ]] && args+=(--volumes)
  compose "${args[@]}"
}

cmd_status() {
  require_docker
  compose --profile judgehost ps
}

cmd_creds() {
  require_docker
  docker inspect "$DOMSERVER_CONTAINER" >/dev/null 2>&1 ||
    die 'the domserver container is not running; run "domjudge.sh up" first.'
  print_creds
}

cmd_logs() {
  require_docker
  local service="${1:-domserver}"
  [[ $# -gt 0 ]] && shift || true
  compose --profile judgehost logs "$@" "$service"
}

cmd_shell() {
  require_docker
  local service="${1:-domserver}"
  compose --profile judgehost exec "$service" bash
}

main() {
  local cmd="${1:-}"
  [[ $# -gt 0 ]] && shift || true

  case "$cmd" in
    up) cmd_up "$@" ;;
    down) cmd_down "$@" ;;
    nuke) cmd_down --volumes ;;
    restart)
      cmd_down
      cmd_up "$@"
      ;;
    status) cmd_status ;;
    creds) cmd_creds ;;
    logs) cmd_logs "$@" ;;
    shell) cmd_shell "$@" ;;
    ''|-h|--help|help) usage ;;
    *)
      usage >&2
      die "unknown command: $cmd"
      ;;
  esac
}

main "$@"
